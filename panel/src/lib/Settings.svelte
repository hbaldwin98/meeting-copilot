<script lang="ts">
  import { onMount } from "svelte";
  import { engine, type Field } from "$lib/engine.svelte";

  let { opacity = $bindable() }: { opacity: number } = $props();

  const groups = $derived(
    engine.settings.reduce<Record<string, Field[]>>((acc, f) => ((acc[f.group] ??= []).push(f), acc), {}),
  );
  const opt = (o: string | [string, string]) => (Array.isArray(o) ? o : [o, o]);
  const pretty = (v: string) => v.replace(/^([ab])([fm])_/, (_, r, g) => `${r === "a" ? "US" : "UK"} ${g === "f" ? "♀" : "♂"} `).replace(/^\w|(?<= )\w/g, (s) => s.toUpperCase());

  onMount(() => engine.loadSettings());
</script>

<div class="space-y-5 px-4 pt-1 pb-4">
  <section>
    <h2 class="group-title">Appearance</h2>
    <div class="field">
      <span>Window opacity</span>
      <div class="flex items-center gap-2">
        <input type="range" min="0.4" max="1" step="0.02" bind:value={opacity} class="w-28" />
        <span class="w-8 text-right font-mono text-[11px] text-faint tabular-nums">{Math.round(opacity * 100)}%</span>
      </div>
    </div>
  </section>

  {#each Object.entries(groups) as [group, fields]}
    <section>
      <h2 class="group-title">{group}</h2>
      {#each fields as f (f.key)}
        <label class="field">
          <span class="min-w-0">
            {f.label}
            {#if !f.live}<span class="ml-1 text-[10px] text-faint" title="Takes effect after restarting the engine">↻</span>{/if}
          </span>
          {#if f.type === "bool"}
            <button type="button" role="switch" aria-checked={!!f.value} aria-label={f.label} onclick={() => engine.set(f.key, !f.value)}
              class="relative h-[18px] w-8 shrink-0 rounded-full transition-colors {f.value ? 'bg-white/80' : 'bg-white/15'}">
              <span class="absolute top-[2px] size-[14px] rounded-full transition-all {f.value ? 'left-[16px] bg-neutral-900' : 'left-[2px] bg-white/70'}"></span>
            </button>
          {:else if f.type === "select"}
            <div class="flex items-center gap-1.5">
              {#if f.key === "voice.voice"}
                <button type="button" title="Listen to this voice" aria-label="Listen to this voice" onclick={(e) => { e.preventDefault(); engine.previewVoice(f.value); }}
                  class="grid size-[26px] shrink-0 place-items-center rounded-md bg-white/[0.07] text-white/70 ring-1 ring-white/[0.08] ring-inset hover:bg-white/[0.14] hover:text-white">
                  <svg viewBox="0 0 16 16" class="size-3"><path d="M5 3.5v9l7-4.5z" fill="currentColor" /></svg>
                </button>
              {/if}
              <select value={f.value ?? ""} onchange={(e) => engine.set(f.key, e.currentTarget.value)} class="control max-w-[170px]">
                {#each f.options ?? [] as o}
                  {@const [v, label] = opt(o)}
                  <option value={v}>{f.key === "voice.voice" ? pretty(label) : label}</option>
                {/each}
              </select>
            </div>
          {:else if f.type === "range"}
            <div class="flex items-center gap-2">
              <input type="range" min={f.min} max={f.max} step={f.step} value={f.value} class="w-24"
                onchange={(e) => engine.set(f.key, +e.currentTarget.value)} />
              <span class="w-8 text-right font-mono text-[11px] text-faint tabular-nums">{(+f.value).toFixed(2)}</span>
            </div>
          {:else if f.type === "number"}
            <input type="number" min={f.min} max={f.max} step={f.step} value={f.value}
              onchange={(e) => engine.set(f.key, +e.currentTarget.value)} class="control w-20 text-right tabular-nums" />
          {:else if f.type === "list"}
            <input value={(f.value ?? []).join(", ")} onchange={(e) => engine.set(f.key, e.currentTarget.value.split(",").map((s) => s.trim()).filter(Boolean))}
              class="control w-[170px]" />
          {/if}
        </label>
      {/each}
    </section>
  {:else}
    <p class="text-[12px] text-faint">{engine.connected ? "Loading…" : "Engine offline: start it to change settings."}</p>
  {/each}

  {#if engine.restartPending}
    <div class="flex items-center justify-between gap-3 rounded-lg bg-amber-300/10 px-3 py-2.5 text-[12px] text-amber-100/90 ring-1 ring-amber-200/15 ring-inset">
      Some changes apply after a restart.
      <button class="rounded-md bg-amber-200/15 px-2.5 py-1 text-[11.5px] font-medium hover:bg-amber-200/25" onclick={() => engine.restart()}>Restart engine</button>
    </div>
  {/if}
</div>

<style>
  @reference "../app.css";
  .group-title {
    @apply mb-1.5 text-[11px] font-medium tracking-wide text-faint uppercase;
  }
  .field {
    @apply flex min-h-9 items-center justify-between gap-3 border-b border-hair text-[12.5px] text-white/80;
  }
  .control {
    @apply rounded-md bg-white/[0.07] px-2 py-1 text-[12px] text-white/90 ring-1 ring-white/[0.08] outline-none ring-inset focus:ring-white/25;
  }
  select.control option {
    background: #1d1d21;
  }
  input[type="range"] {
    accent-color: rgb(255 255 255 / 0.8);
    height: 4px;
  }
</style>
