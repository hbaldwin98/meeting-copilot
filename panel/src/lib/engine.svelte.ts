// Client side of the engine's WebSocket seam. All panel state lives here;
// components only read it and call the command functions.

export type TaskState = "running" | "done" | "failed" | "cancelled";

export interface Task {
  id: string;
  title: string;
  kind: string;
  state: TaskState;
  notes: string[];
  cardId?: string;
  error?: string;
  startedAt: number;
  endedAt?: number;
}

export interface Card {
  id: string;
  headline: string;
  body_md: string;
  sources: string[];
  task_id: string | null;
  kind: string;
  at: number;
}

export interface Topic {
  id: number;
  title: string;
  summary: string;
  t0: number;
  t1: number;
  related: number[];
}

export interface Cost {
  total: number;
  scribe: number;
  listener: number;
  agents: number;
  budget: number;
}

export interface Field {
  group: string;
  key: string;
  label: string;
  type: "bool" | "select" | "range" | "number" | "list";
  value: any;
  live: boolean;
  options?: (string | [string, string])[];
  min?: number;
  max?: number;
  step?: number;
}

export interface Line {
  channel: "me" | "them";
  text: string;
  final: boolean;
}

const URL = "ws://127.0.0.1:8765";

class Engine {
  connected = $state(false);
  status = $state<{ state: string; detail: string }>({ state: "offline", detail: "" });
  tasks = $state<Task[]>([]);
  cards = $state<Card[]>([]);
  lines = $state<Line[]>([]);
  partial = $state<Record<string, string>>({});
  topics = $state<Topic[]>([]);
  topicDetail = $state<Record<number, string>>({});
  cost = $state<Cost | null>(null);
  voice = $state<{ on: boolean; mode: string } | null>(null);
  settings = $state<Field[]>([]);
  restartPending = $state(false);

  running = $derived(this.tasks.filter((t) => t.state === "running"));
  paused = $derived(this.status.state === "paused");

  #ws: WebSocket | null = null;
  #retry = 500;

  connect() {
    const ws = new WebSocket(URL);
    this.#ws = ws;
    ws.onopen = () => {
      this.connected = true;
      this.#retry = 500;
      // the engine replays history on connect; start clean to avoid duplicates
      this.tasks = [];
      this.cards = [];
    };
    ws.onclose = () => {
      this.connected = false;
      this.status = { state: "offline", detail: "" };
      setTimeout(() => this.connect(), (this.#retry = Math.min(this.#retry * 2, 5000)));
    };
    ws.onmessage = (m) => this.#handle(JSON.parse(m.data));
  }

  #task(id: string) {
    return this.tasks.find((t) => t.id === id);
  }

  #handle(e: any) {
    switch (e.type) {
      case "transcript":
        if (e.final) {
          this.lines = [...this.lines.slice(-49), { channel: e.channel, text: e.text, final: true }];
          this.partial[e.channel] = "";
        } else {
          this.partial[e.channel] = e.text;
        }
        break;
      case "card":
        this.cards = [{ ...e, at: Date.now() }, ...this.cards];
        break;
      case "task.started":
        this.tasks = [
          { id: e.id, title: e.title, kind: e.kind, state: "running", notes: [], startedAt: Date.now() },
          ...this.tasks,
        ];
        break;
      case "task.progress": {
        const t = this.#task(e.id);
        if (t) t.notes = [...t.notes.slice(-19), e.note];
        break;
      }
      case "task.done":
      case "task.failed":
      case "task.cancelled": {
        const t = this.#task(e.id);
        if (t) {
          t.state = e.type.slice(5) as TaskState;
          t.cardId = e.card_id;
          t.error = e.error;
          t.endedAt = Date.now();
        }
        break;
      }
      case "topics":
        this.topics = e.items;
        break;
      case "topic.detail":
        this.topicDetail[e.id] = e.text;
        break;
      case "settings":
        this.settings = e.fields;
        this.restartPending = e.restart;
        break;
      case "voice":
        this.voice = { on: e.on, mode: e.mode };
        break;
      case "cost":
        this.cost = e;
        break;
      case "status":
        this.status = { state: e.state, detail: e.detail ?? "" };
        break;
    }
  }

  #send(cmd: object) {
    if (this.#ws?.readyState === WebSocket.OPEN) this.#ws.send(JSON.stringify(cmd));
  }

  ask(prompt = "") {
    this.#send({ cmd: "ask", prompt });
  }
  cancel(id: string) {
    this.#send({ cmd: "cancel", id });
  }
  loadTopic(id: number) {
    this.#send({ cmd: "topic", id });
  }
  speak(text: string) {
    this.#send({ cmd: "speak", text });
  }
  previewVoice(voice: string) {
    this.#send({ cmd: "preview_voice", voice });
  }
  stopSpeaking() {
    this.#send({ cmd: "stop_speaking" });
  }
  toggleVoice() {
    this.#send({ cmd: "voice", on: !this.voice?.on });
  }
  loadSettings() {
    this.#send({ cmd: "settings" });
  }
  set(key: string, value: unknown) {
    this.#send({ cmd: "set", patch: { [key]: value } });
  }
  restart() {
    this.#send({ cmd: "restart" });
  }
  togglePause() {
    this.#send({ cmd: this.paused ? "resume" : "pause" });
  }
}

export const engine = new Engine();
