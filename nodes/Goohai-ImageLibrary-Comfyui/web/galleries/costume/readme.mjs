import { marked, Renderer } from "./marked.mjs";

const escape = value => String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

export async function openReadme(owner, url) {
  if (owner.querySelector(".ghil-readme")) return;
  const dialog = document.createElement("dialog");
  dialog.className = "ghil-readme";
  dialog.innerHTML = `<style>
    .ghil-readme{width:min(760px,calc(100% - 32px));max-height:86vh;padding:0;border:1px solid #dce2eb;border-radius:18px;background:#fff;color:#263449;box-shadow:0 24px 80px #0f142338;overflow:auto;font:14px/1.8 "Microsoft YaHei",sans-serif}
    .ghil-readme::backdrop{background:#0f121c8c;backdrop-filter:blur(5px)}
    .ghil-readme:focus{outline:none}.ghil-readme header{position:sticky;top:0;display:flex;align-items:center;justify-content:space-between;padding:18px 24px;background:#fff;border-bottom:1px solid #dce2eb;z-index:1}
    .ghil-readme header strong{font-size:18px}.ghil-readme header button{width:34px;height:34px;border:0;border-radius:9px;background:#f5f7fb;color:#263449;font-size:24px;cursor:pointer}
    .ghil-readme article{padding:20px 26px 28px;overflow-wrap:anywhere}.ghil-readme h1,.ghil-readme h2{border-bottom:1px solid #dce2eb;padding-bottom:8px;line-height:1.5}.ghil-readme h1{font-size:22px}.ghil-readme h2{font-size:19px}.ghil-readme h3{font-size:16px}
    .ghil-readme a{color:#0969da}.ghil-readme table{display:block;max-width:100%;overflow:auto;border-collapse:collapse}.ghil-readme th,.ghil-readme td{border:1px solid #dce2eb;padding:6px 12px}.ghil-readme tr:nth-child(2n){background:#f6f8fa}
    .ghil-readme pre{padding:16px;background:#f6f8fa;border-radius:6px;overflow:auto}.ghil-readme code{font-family:Consolas,monospace;font-size:13px}.ghil-readme blockquote{margin-left:0;padding-left:16px;border-left:4px solid #dce2eb;color:#647188}
  </style><header><strong>版权 · 致谢</strong><button type="button" aria-label="关闭">×</button></header><article role="document">正在读取 README…</article>`;
  const close = () => { dialog.close(); dialog.remove(); };
  dialog.querySelector("button").onclick = close;
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  dialog.addEventListener("click", event => {
    const box = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) close();
  });
  owner.append(dialog);
  dialog.showModal();
  const article = dialog.querySelector("article");
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`README 读取失败：HTTP ${response.status}`);
    const source = await response.text();
    if (!dialog.isConnected) return;
    const renderer = new Renderer();
    const repo = "https://github.com/Deeyu/ai-costume-gallery-zh/blob/main/";
    renderer.link = function (token) {
      const target = new URL(token.href, repo);
      const text = this.parser.parseInline(token.tokens);
      return ["http:", "https:", "mailto:"].includes(target.protocol) ? `<a href="${escape(target.href)}" target="_blank" rel="noopener noreferrer">${text}</a>` : text;
    };
    renderer.image = token => {
      const target = new URL(token.href, repo);
      return ["http:", "https:"].includes(target.protocol) ? `<a href="${escape(target.href)}" target="_blank" rel="noopener noreferrer">${escape(token.text)}</a>` : escape(token.text);
    };
    renderer.html = () => "";
    article.innerHTML = marked.parse(source, { renderer, gfm: true });
  } catch (error) {
    article.textContent = error.message;
  }
}
