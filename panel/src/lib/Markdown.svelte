<script lang="ts">
  import { marked } from "marked";
  import DOMPurify from "dompurify";
  import { openUrl } from "@tauri-apps/plugin-opener";

  let { md }: { md: string } = $props();
  const html = $derived(DOMPurify.sanitize(marked.parse(md, { async: false }) as string));

  function onclick(e: MouseEvent) {
    const a = (e.target as HTMLElement).closest("a");
    if (a?.href) {
      e.preventDefault();
      openUrl(a.href).catch(() => window.open(a.href, "_blank"));
    }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div
  class="prose prose-invert prose-sm max-w-none text-[12.5px] leading-relaxed text-white/70 select-text prose-p:my-1.5 prose-ul:my-1.5 prose-ul:pl-4 prose-li:my-0.5 prose-li:marker:text-white/30 prose-strong:text-white/90 prose-strong:font-medium prose-a:text-white/85 prose-a:underline prose-a:decoration-white/25 hover:prose-a:decoration-white/60 prose-headings:text-sm prose-code:text-white/85 prose-code:before:content-none prose-code:after:content-none"
  {onclick}
>
  {@html html}
</div>
