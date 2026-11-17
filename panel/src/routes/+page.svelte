<script lang="ts">
  import { onMount, tick } from "svelte";
  import { slide } from "svelte/transition";
  import { isTauri } from "@tauri-apps/api/core";
  import { engine, type Card, type Task } from "$lib/engine.svelte";
  import Markdown from "$lib/Markdown.svelte";
  import SettingsView from "$lib/Settings.svelte";

  const W = 380, H_FULL = 660, H_MINI = 44;
  const TABS = [
    { key: "feed", label: "Feed" },
    { key: "tasks", label: "Agents" },
    { key: "topics", label: "Topics" },
  ] as const;
  type Tab = (typeof TABS)[number]["key"];

  const KIND: Record<string, string> = {
    instant: "bg-violet-300", lookup: "bg-sky-300", research: "bg-blue-300",
    docs: "bg-amber-300", context: "bg-teal-300", cached: "bg-emerald-300",
  };

  let collapsed = $state(false);
  let view = $state<"main" | "settings">("main");
  let opacity = $state(0.82);
  try { opacity = +(localStorage.getItem("opacity") ?? 0.82); } catch {}
  $effect(() => {
    document.documentElement.style.setProperty("--opacity", String(opacity));
    try { localStorage.setItem("opacity", String(opacity)); } catch {}
  });
  let tab = $state<Tab>("feed");
  let openTopic = $state<number | null>(null);
  let openCard = $state<string | null>(null);
  let openTask = $state<string | null>(null);
  let prompt = $state("");
  let input: HTMLInputElement | undefined = $state();
  let now = $state(Date.now());

  const latest = $derived(engine.cards[0]);
  const tail = $derived(engine.lines.slice(-2));
  const livePartial = $derived(engine.partial.them || engine.partial.me || "");
  const tabIndex = $derived(TABS.findIndex((t) => t.key === tab));
  const counts = $derived({ feed: engine.cards.length, tasks: engine.tasks.length, topics: engine.topics.length });
  const status = $derived(
    !engine.connected ? { c: "bg-white/25", label: "Offline" }
      : engine.paused ? { c: "bg-amber-300/90", label: "Paused" }
      : engine.status.state === "thinking" ? { c: "bg-white/80 animate-pulse", label: "Thinking" }
      : engine.status.state === "error" ? { c: "bg-red-400", label: "Error" }
      : { c: "bg-emerald-400/90", label: "Listening" },
  );
  const costLabel = $derived(engine.cost ? `$${engine.cost.total.toFixed(2)}${engine.cost.budget > 0 ? ` / $${engine.cost.budget}` : ""}` : "");
  const costTitle = $derived(engine.cost
    ? `scribe $${engine.cost.scribe.toFixed(3)} · listener $${engine.cost.listener.toFixed(3)} · agents $${engine.cost.agents.toFixed(3)}`
    : "");

  async function win() {
    if (!isTauri()) return null;
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    return getCurrentWindow();
  }

  async function setCollapsed(v: boolean) {
    collapsed = v;
    const w = await win();
    if (w) {
      const { LogicalSize } = await import("@tauri-apps/api/dpi");
      await w.setSize(new LogicalSize(W, v ? H_MINI : H_FULL));
    }
  }

  async function focusAsk() {
    if (collapsed) await setCollapsed(false);
    const w = await win();
    await w?.show();
    await w?.setFocus();
    await tick();
    input?.focus();
  }

  function submit(e: SubmitEvent) {
    e.preventDefault();
    engine.ask(prompt);
    prompt = "";
    tab = "tasks";
  }

  function showCard(id?: string) {
    if (!id) return;
    tab = "feed";
    openCard = id;
    tick().then(() => document.getElementById(`card-${id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  }

  function ago(ts: number) {
    const s = Math.max(0, Math.round((now - ts) / 1000));
    return s < 5 ? "now" : s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${Math.round(s / 3600)}h`;
  }
  const dur = (t: Task) => `${Math.round(((t.endedAt ?? now) - t.startedAt) / 1000)}s`;
  const taskOf = (c: Card) => engine.tasks.find((t) => t.id === c.task_id);
  const kindOf = (c: Card) => c.kind ?? taskOf(c)?.kind ?? "instant";
  const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };

  onMount(() => {
    if (!isTauri()) document.body.classList.add("no-tauri");
    engine.connect();
    const clock = setInterval(() => (now = Date.now()), 1000);
    (async () => {
      if (!isTauri()) return;
      const gs = await import("@tauri-apps/plugin-global-shortcut");
      await gs.unregisterAll();
      await gs.register("CommandOrControl+Shift+Space", (e) => {
        if (e.state === "Pressed") { engine.ask(""); tab = "tasks"; }
      });
      await gs.register("CommandOrControl+Shift+K", (e) => e.state === "Pressed" && focusAsk());
      await gs.register("CommandOrControl+Shift+L", async (e) => {
        if (e.state !== "Pressed") return;
        const w = await win();
        if (!w) return;
        (await w.isVisible()) ? w.hide() : (await w.show(), w.setFocus());
      });
      await gs.register("CommandOrControl+Shift+P", (e) => e.state === "Pressed" && engine.togglePause());
      const { listen } = await import("@tauri-apps/api/event");
      await listen<string>("tray", (e) => {
        if (e.payload === "ask") { engine.ask(""); tab = "tasks"; view = "main"; }
        else if (e.payload === "pause") engine.togglePause();
        else if (e.payload === "settings") { if (collapsed) setCollapsed(false); view = "settings"; }
      });
      await gs.register("CommandOrControl+Shift+Period", (e) => e.state === "Pressed" && engine.stopSpeaking());
    })();
    return () => clearInterval(clock);
  });
</script>

<svelte:window
  onkeydown={(e) => e.key === "Escape" && (openCard = openTask = null)}
  oncontextmenu={(e) => { if (!(e.target as HTMLElement).closest("input, textarea")) e.preventDefault(); }}
/>

{#snippet icon(path: string, cls = "size-[14px]")}
  <svg viewBox="0 0 16 16" class={cls} fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">{@html path}</svg>
{/snippet}

<div class="flex h-screen flex-col">
  <!-- title bar -->
  <header data-tauri-drag-region class="flex h-11 shrink-0 items-center gap-2.5 pr-1.5 pl-4">
    <span class="size-[7px] shrink-0 rounded-full {status.c} shadow-[0_0_8px_1px_currentColor]" style="color: rgb(255 255 255 / 0.15)" title={status.label}></span>
    {#if collapsed}
      <button class="min-w-0 flex-1 truncate text-left text-[13px] text-fg" onclick={() => { setCollapsed(false); showCard(latest?.id); }}>
        {latest?.headline ?? status.label}
      </button>
    {:else}
      <span data-tauri-drag-region class="text-[13px] font-semibold">Copilot</span>
      <span data-tauri-drag-region class="text-[12px] text-faint">{status.label}</span>
      <span data-tauri-drag-region class="flex-1"></span>
      {#if costLabel}<span title={costTitle} class="mr-1 font-mono text-[11px] text-faint tabular-nums">{costLabel}</span>{/if}
    {/if}
    {#if engine.running.length}
      <button class="flex items-center gap-1.5 px-1.5 text-[11px] text-dim" title="Running agents" onclick={() => { setCollapsed(false); tab = "tasks"; }}>
        <span class="size-2.5 animate-spin rounded-full border-[1.5px] border-white/60 border-t-transparent"></span>{engine.running.length}
      </button>
    {/if}
    {#if engine.voice}
      <button class="ibtn" class:off={!engine.voice.on} title={engine.voice.on ? "Voice on · Ctrl+Shift+. stops" : "Voice off"} onclick={() => engine.toggleVoice()}>
        {@render icon(engine.voice.on
          ? '<path d="M3 6.2h2.2L8.5 3.5v9L5.2 9.8H3z"/><path d="M10.8 5.8a3.2 3.2 0 0 1 0 4.4M12.5 4.1a5.6 5.6 0 0 1 0 7.8"/>'
          : '<path d="M3 6.2h2.2L8.5 3.5v9L5.2 9.8H3z"/><path d="M11 6.3l2.8 3.4M13.8 6.3L11 9.7"/>')}
      </button>
    {/if}
    <button class="ibtn {view === 'settings' ? '!bg-white/[0.1] !text-white' : ''}" title="Settings" onclick={() => { if (collapsed) setCollapsed(false); view = view === "settings" ? "main" : "settings"; }}>
      {@render icon('<path d="M2.5 5h6.5M12 5h1.5M2.5 11h1.5M7 11h6.5"/><circle cx="10.5" cy="5" r="1.5"/><circle cx="5.5" cy="11" r="1.5"/>')}
    </button>
    <button class="ibtn" title="Pause / resume · Ctrl+Shift+P" onclick={() => engine.togglePause()}>
      {@render icon(engine.paused ? '<path d="M5.5 3.8v8.4l6.5-4.2z"/>' : '<path d="M6 4v8M10 4v8"/>')}
    </button>
    <button class="ibtn" title={collapsed ? "Expand" : "Collapse"} onclick={() => setCollapsed(!collapsed)}>
      {@render icon(collapsed ? '<path d="M4.5 6.5L8 10l3.5-3.5"/>' : '<path d="M4 8h8"/>')}
    </button>
    <button class="ibtn close" title="Hide · Ctrl+Shift+L" onclick={async () => (await win())?.hide()}>
      {@render icon('<path d="M5 5l6 6M11 5l-6 6"/>')}
    </button>
  </header>

  {#if !collapsed && view === "settings"}
    <main class="min-h-0 flex-1 overflow-y-auto"><SettingsView bind:opacity /></main>
  {:else if !collapsed}
    <nav class="relative mx-3 mb-2.5 grid grid-cols-3 rounded-lg bg-black/25 p-[3px] ring-1 ring-white/[0.06] ring-inset">
      <span class="absolute inset-y-[3px] left-[3px] rounded-md bg-white/[0.1] ring-1 ring-white/[0.08] ring-inset transition-transform duration-200 ease-out"
        style="width: calc((100% - 6px) / 3); transform: translateX({tabIndex * 100}%)"></span>
      {#each TABS as t}
        <button class="relative py-[5px] text-[12px] transition-colors {tab === t.key ? 'text-fg' : 'text-faint hover:text-dim'}" onclick={() => (tab = t.key)}>
          {t.label}{#if counts[t.key]}<span class="ml-1.5 tabular-nums opacity-60">{counts[t.key]}</span>{/if}
        </button>
      {/each}
    </nav>

    <main class="min-h-0 flex-1 space-y-1.5 overflow-y-auto px-3 pb-3">
      {#if tab === "feed"}
        {#each engine.cards as c (c.id)}
          <article id="card-{c.id}" class="row" class:open={openCard === c.id}>
            <button class="w-full px-3.5 py-3 text-left" onclick={() => (openCard = openCard === c.id ? null : c.id)}>
              <h3 class="text-[13px] leading-snug font-medium text-fg">{c.headline}</h3>
              <div class="mt-1.5 flex gap-2 text-[11px] text-faint">
                <span class="flex items-center gap-1.5 text-dim"><span class="size-1.5 rounded-full {KIND[kindOf(c)] ?? KIND.instant}"></span>{kindOf(c)}</span>
                {#if c.sources.length}<span class="truncate">{host(c.sources[0])}{c.sources.length > 1 ? ` +${c.sources.length - 1}` : ""}</span>{/if}
                <span class="ml-auto tabular-nums">{ago(c.at)}</span>
              </div>
            </button>
            {#if openCard === c.id}
              <div transition:slide={{ duration: 150 }} class="mx-3.5 border-t border-hair pt-2 pb-3">
                <Markdown md={c.body_md} />
                <button class="link mt-2" onclick={() => engine.speak(`${c.headline}. ${c.body_md.split("Sources:")[0]}`)}>Read aloud</button>
              </div>
            {/if}
          </article>
        {:else}
          <div class="px-6 pt-20 text-center">
            <p class="text-[13px] text-dim">Nothing yet</p>
            <p class="mt-1 text-[12px] leading-relaxed text-faint">Cards show up when a name, topic or open question comes up.</p>
            <p class="mt-4 text-[11px] text-faint"><kbd>Ctrl</kbd> <kbd>Shift</kbd> <kbd>Space</kbd> asks about the last 90 s</p>
          </div>
        {/each}

      {:else if tab === "tasks"}
        {#each engine.tasks as t (t.id)}
          <article class="row">
            <div class="flex items-center gap-3 px-3.5 py-2.5">
              <span class="grid size-3 shrink-0 place-items-center">
                {#if t.state === "running"}
                  <span class="size-3 animate-spin rounded-full border-[1.5px] border-white/60 border-t-transparent"></span>
                {:else}
                  <span class="size-1.5 rounded-full {t.state === 'done' ? 'bg-emerald-400/90' : t.state === 'failed' ? 'bg-red-400' : 'bg-white/30'}"></span>
                {/if}
              </span>
              <button class="min-w-0 flex-1 text-left" onclick={() => (openTask = openTask === t.id ? null : t.id)}>
                <div class="truncate text-[13px]">{t.title}</div>
                <div class="flex items-center gap-1.5 truncate text-[11px] text-faint"><span class="size-1.5 shrink-0 rounded-full {KIND[t.kind] ?? KIND.instant}"></span>{t.kind} · {dur(t)} · {t.error ?? t.notes.at(-1) ?? t.state}</div>
              </button>
              {#if t.state === "running"}
                <button class="link" onclick={() => engine.cancel(t.id)}>Cancel</button>
              {:else if t.cardId}
                <button class="link" onclick={() => showCard(t.cardId)}>Open</button>
              {/if}
            </div>
            {#if openTask === t.id && t.notes.length}
              <ol transition:slide={{ duration: 150 }} class="space-y-0.5 px-4 pb-2.5 pl-10 font-mono text-[10.5px] text-faint select-text">
                {#each t.notes as n}<li class="truncate">{n}</li>{/each}
              </ol>
            {/if}
          </article>
        {:else}
          <p class="pt-20 text-center text-[12px] text-faint">No agents have run yet</p>
        {/each}

      {:else}
        {#each engine.topics as tp (tp.id)}
          <article class="row">
            <button class="w-full px-3.5 py-3 text-left" onclick={() => { openTopic = openTopic === tp.id ? null : tp.id; if (openTopic) engine.loadTopic(tp.id); }}>
              <h3 class="text-[13px] leading-snug font-medium">{tp.title}</h3>
              <p class="mt-1 text-[12px] leading-relaxed text-dim">{tp.summary}</p>
              {#if tp.related.length}
                <p class="mt-1 text-[11px] text-faint">Related: {tp.related.map((r) => engine.topics.find((x) => x.id === r)?.title ?? `T${r}`).join(", ")}</p>
              {/if}
            </button>
            {#if openTopic === tp.id}
              <pre transition:slide={{ duration: 150 }} class="mx-3.5 mb-3 max-h-64 overflow-auto rounded-md bg-black/20 p-2.5 font-mono text-[10.5px] leading-relaxed whitespace-pre-wrap text-dim select-text">{engine.topicDetail[tp.id] ?? "Loading…"}</pre>
            {/if}
          </article>
        {:else}
          <p class="pt-20 text-center text-[12px] text-faint">Topics build up as audio comes in</p>
        {/each}
      {/if}
    </main>

    <footer class="shrink-0 px-3 pb-3">
      {#if tail.length || livePartial}
        <div class="mb-2 space-y-0.5 px-1 text-[11px] leading-snug text-faint">
          {#each tail as l}<p class="truncate"><span class="text-dim">{l.channel === "me" ? "You" : "Them"}</span> · {l.text}</p>{/each}
          {#if livePartial}<p class="truncate italic">{livePartial}</p>{/if}
        </div>
      {/if}
      <form onsubmit={submit} class="flex items-center gap-1.5 rounded-lg bg-black/25 py-1 pr-1 pl-3 ring-1 ring-white/[0.08] transition ring-inset focus-within:ring-white/25">
        <input bind:this={input} bind:value={prompt} placeholder="Ask Claude…"
          class="min-w-0 flex-1 bg-transparent py-1 text-[13px] outline-none placeholder:text-faint" />
        <button type="submit" title={prompt ? "Ask" : "Ask about right now"}
          class="grid size-7 place-items-center rounded-md bg-white/[0.1] text-white/80 ring-1 ring-white/[0.08] transition ring-inset hover:bg-white/[0.16] hover:text-white">
          {@render icon('<path d="M8 12.5V3.5M4.5 7L8 3.5 11.5 7"/>', "size-3.5")}
        </button>
      </form>
    </footer>
  {/if}
</div>

<style>
  @reference "../app.css";
  .row {
    @apply rounded-[10px] bg-white/[0.045] ring-1 ring-white/[0.06] transition-colors ring-inset hover:bg-white/[0.07];
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.04);
  }
  .row.open {
    @apply bg-white/[0.07] ring-white/[0.1];
  }
  :global(kbd) {
    @apply rounded bg-white/[0.08] px-1.5 py-px font-sans text-[10px] text-white/60 ring-1 ring-white/10 ring-inset;
  }
  :global(.ibtn) {
    @apply grid size-7 place-items-center rounded text-white/55 transition-colors hover:bg-white/[0.08] hover:text-white/90;
  }
  :global(.ibtn.off) {
    @apply text-white/30;
  }
  :global(.ibtn.close:hover) {
    @apply bg-red-600/80 text-white;
  }
  :global(.link) {
    @apply text-[11.5px] text-dim underline decoration-white/20 underline-offset-2 hover:text-fg hover:decoration-white/50;
  }
</style>
