#!/usr/bin/env python3
"""Собирает внешнюю sellrise_docs/ в одну самодостаточную HTML-страницу.

Выход: deploy/sellrise-site/index.html — отдаётся Caddy на demo (только demo-блок).
Внутренние ссылки между .md → якоря одной страницы. Только внешняя дока
(sellrise_internal/ НЕ включается). Перегенерировать: python3 docs/gen_sellrise_site.py
"""
import html
import os
import re

ORDER = [
    ("sellrise_docs/README.md", "readme", "Обзор"),
    ("sellrise_docs/integration/b2b-integration-architecture.md", "b2b-integration-architecture", "Архитектура интеграции"),
    ("sellrise_docs/integration/authentication-and-access.md", "authentication-and-access", "Аутентификация и доступы"),
    ("sellrise_docs/integration/data-requirements.md", "data-requirements", "Требования к данным"),
    ("sellrise_docs/integration/realtime-event-ingestion.md", "realtime-event-ingestion", "Приём событий (real-time)"),
    ("sellrise_docs/integration/batch-data-ingestion.md", "batch-data-ingestion", "Batch-загрузка / бэкфилл"),
    ("sellrise_docs/integration/predictions-delivery.md", "predictions-delivery", "Доставка предсказаний"),
]
# карта .md → якорь (basename и относительный путь)
LINKMAP = {}
for path, anchor, _ in ORDER:
    base = os.path.basename(path)
    LINKMAP[base] = "#" + anchor
    LINKMAP["integration/" + base] = "#" + anchor
    LINKMAP[path] = "#" + anchor


def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", lambda m: "<code>" + m.group(1) + "</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)

    def link(m):
        text, url = m.group(1), m.group(2)
        url = LINKMAP.get(url, url)
        return f'<a href="{url}">{text}</a>'

    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, t)
    return t


def render(md):
    out = []
    lines = md.split("\n")
    i, n = 0, len(lines)
    in_code = False
    while i < n:
        ln = lines[i]
        if ln.startswith("```"):
            if not in_code:
                out.append("<pre><code>")
                in_code = True
            else:
                out.append("</code></pre>")
                in_code = False
            i += 1
            continue
        if in_code:
            out.append(html.escape(ln, quote=False))
            i += 1
            continue
        # таблица
        if ln.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|?\s*$", lines[i + 1]):
            header = [c.strip() for c in ln.strip().strip("|").split("|")]
            out.append('<table><thead><tr>' + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr></thead><tbody>")
            i += 2
            while i < n and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue
        # заголовки
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        # цитата
        if ln.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(buf)) + "</blockquote>")
            continue
        # списки
        if re.match(r"^\s*[-*]\s+", ln):
            out.append("<ul>")
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                out.append("<li>" + inline(re.sub(r"^\s*[-*]\s+", "", lines[i])) + "</li>")
                i += 1
            out.append("</ul>")
            continue
        if re.match(r"^\s*\d+\.\s+", ln):
            out.append("<ol>")
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                out.append("<li>" + inline(re.sub(r"^\s*\d+\.\s+", "", lines[i])) + "</li>")
                i += 1
            out.append("</ol>")
            continue
        if ln.strip() == "":
            i += 1
            continue
        # абзац (склеиваем до пустой строки/блочного элемента)
        buf = [ln]
        i += 1
        while i < n and lines[i].strip() and not re.match(r"^(#{1,6}\s|```|>|\||\s*[-*]\s|\s*\d+\.\s)", lines[i]):
            buf.append(lines[i])
            i += 1
        out.append("<p>" + inline(" ".join(buf)) + "</p>")
    return "\n".join(out)


def main():
    toc, sections = [], []
    for path, anchor, title in ORDER:
        md = open(path, encoding="utf-8").read()
        toc.append(f'<li><a href="#{anchor}">{html.escape(title)}</a></li>')
        sections.append(f'<section id="{anchor}">\n{render(md)}\n</section>')

    doc = TEMPLATE.replace("{{TOC}}", "\n".join(toc)).replace("{{BODY}}", "\n".join(sections))
    os.makedirs("deploy/sellrise-site", exist_ok=True)
    with open("deploy/sellrise-site/index.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("✓ deploy/sellrise-site/index.html", len(doc), "байт,", len(ORDER), "разделов")


TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="color-scheme" content="dark">
<title>Sellrise — интеграционная документация</title>
<style>
 :root{
   --bg:#08090c; --panel:#0d0f14; --surface:#12151b; --surface2:#161a21;
   --ink:#e9ebf1; --muted:#98a1b2; --faint:#626b7c;
   --line:rgba(255,255,255,.075); --line2:rgba(255,255,255,.13);
   --accent:#5aa2ff; --cyan:#37e0cf; --accent-soft:rgba(90,162,255,.14);
   --radius:14px;
 }
 *{box-sizing:border-box}
 html{scroll-behavior:smooth; scroll-padding-top:26px}
 body{margin:0;color:var(--ink);background:var(--bg);
   font:15px/1.68 "Inter",-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
   -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;}
 /* фон: near-black + свечение + тонкая сетка */
 body::before{content:"";position:fixed;inset:0;z-index:-2;background:var(--bg)}
 body::after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
   background:
     radial-gradient(1000px 560px at 50% -12%, rgba(90,162,255,.16), transparent 60%),
     radial-gradient(760px 420px at 100% -5%, rgba(55,224,207,.08), transparent 55%),
     linear-gradient(rgba(255,255,255,.022) 1px, transparent 1px) 0 0/44px 44px,
     linear-gradient(90deg, rgba(255,255,255,.022) 1px, transparent 1px) 0 0/44px 44px;
   -webkit-mask:radial-gradient(1200px 700px at 50% 0, #000 30%, transparent 78%);
           mask:radial-gradient(1200px 700px at 50% 0, #000 30%, transparent 78%);}
 ::selection{background:rgba(90,162,255,.32);color:#fff}
 ::-webkit-scrollbar{width:10px;height:10px}
 ::-webkit-scrollbar-thumb{background:#1e2229;border-radius:8px;border:2px solid var(--bg)}
 ::-webkit-scrollbar-thumb:hover{background:#2a2f38}

 /* hero */
 .hero{border-bottom:1px solid var(--line);position:relative;overflow:hidden}
 .hero-inner{max-width:1180px;margin:0 auto;padding:46px 32px 34px}
 .brand{font-size:30px;font-weight:800;letter-spacing:-.02em;
   background:linear-gradient(94deg,#fff 6%,var(--accent) 52%,var(--cyan));
   -webkit-background-clip:text;background-clip:text;color:transparent;width:max-content}
 .brand::after{content:"";display:inline-block;width:7px;height:7px;margin-left:2px;border-radius:50%;
   background:var(--cyan);box-shadow:0 0 12px var(--cyan);vertical-align:middle}
 .tagline{margin-top:10px;color:var(--muted);font-size:14.5px;max-width:660px}

 .wrap{display:grid;grid-template-columns:262px 1fr;max-width:1180px;margin:0 auto;gap:0}
 /* sticky TOC */
 nav.toc{position:sticky;top:0;align-self:start;height:100vh;overflow:auto;
   padding:30px 14px 40px 32px;border-right:1px solid var(--line)}
 .toc-title{font-size:11px;text-transform:uppercase;letter-spacing:.14em;color:var(--faint);margin:0 0 14px;padding-left:12px}
 nav.toc ul{list-style:none;margin:0;padding:0}
 nav.toc li{margin:1px 0}
 nav.toc a{color:var(--muted);text-decoration:none;font-size:13.5px;display:block;padding:8px 12px;border-radius:9px;
   position:relative;transition:color .15s,background .15s}
 nav.toc a:hover{color:var(--ink);background:rgba(255,255,255,.04)}
 nav.toc a.active{color:#fff;background:linear-gradient(90deg,var(--accent-soft),transparent)}
 nav.toc a.active::before{content:"";position:absolute;left:0;top:6px;bottom:6px;width:2.5px;border-radius:3px;
   background:linear-gradient(var(--accent),var(--cyan));box-shadow:0 0 10px rgba(90,162,255,.6)}

 main{min-width:0;padding:34px 40px 96px}
 section{padding-bottom:34px;margin-bottom:34px;border-bottom:1px solid var(--line)}
 section:last-child{border-bottom:none}
 h1{font-size:25px;font-weight:750;letter-spacing:-.01em;margin:.1em 0 .6em}
 h2{font-size:19px;font-weight:680;margin:1.7em 0 .6em;padding-left:14px;position:relative}
 h2::before{content:"";position:absolute;left:0;top:.28em;height:.85em;width:3px;border-radius:3px;
   background:linear-gradient(var(--accent),var(--cyan))}
 h3{font-size:15.5px;font-weight:650;color:#dfe3ec;margin:1.3em 0 .45em}
 p{margin:.65em 0;color:#cfd4de}
 strong{color:#fff;font-weight:650}
 a{color:var(--accent);text-decoration:none;border-bottom:1px solid rgba(90,162,255,.28)}
 a:hover{color:#8dbcff;border-bottom-color:#8dbcff}

 code{background:var(--surface2);color:#a9e9e0;padding:.13em .42em;border-radius:6px;
   font:12.5px/1.5 "JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
   border:1px solid var(--line)}
 pre{background:linear-gradient(180deg,#0f1218,#0c0e13);border:1px solid var(--line2);border-radius:var(--radius);
   padding:16px 18px;overflow:auto;position:relative;box-shadow:0 1px 0 rgba(255,255,255,.03) inset}
 pre::before{content:"";position:absolute;top:13px;left:15px;width:9px;height:9px;border-radius:50%;
   background:#2b3038;box-shadow:15px 0 0 #2b3038,30px 0 0 #2b3038}
 pre code{background:none;padding:0;border:none;color:#cdd6e3;white-space:pre;display:block;margin-top:16px}

 blockquote{margin:1em 0;padding:12px 16px;border:1px solid var(--line);border-left:3px solid var(--accent);
   background:linear-gradient(90deg,rgba(90,162,255,.07),rgba(255,255,255,.01));color:var(--muted);
   border-radius:0 12px 12px 0}
 blockquote strong{color:#dfe6f2}

 .tablewrap,table{margin:1.1em 0}
 table{border-collapse:separate;border-spacing:0;width:100%;font-size:13.5px;display:block;overflow-x:auto;
   border:1px solid var(--line2);border-radius:var(--radius);background:var(--panel)}
 th,td{padding:10px 14px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
 thead th{background:var(--surface);color:#cfd6e3;font-weight:600;white-space:nowrap;
   border-bottom:1px solid var(--line2)}
 tbody tr:last-child td{border-bottom:none}
 tbody tr:hover td{background:rgba(255,255,255,.022)}
 td code,th code{background:rgba(90,162,255,.10);color:#bcd6ff;border-color:rgba(90,162,255,.2)}

 ul,ol{margin:.6em 0;padding-left:1.35em;color:#cfd4de}
 li{margin:.3em 0}
 li::marker{color:var(--accent)}

 footer{max-width:1180px;margin:0 auto;padding:26px 40px 50px;color:var(--faint);font-size:12.5px;
   border-top:1px solid var(--line)}

 @media(max-width:860px){
   .wrap{grid-template-columns:1fr}
   nav.toc{position:static;height:auto;border-right:none;border-bottom:1px solid var(--line);padding:20px 24px}
   main{padding:26px 22px 70px}.hero-inner{padding:38px 22px 28px}footer{padding:22px}
 }
</style>
</head>
<body>
<header class="hero">
  <div class="hero-inner">
    <div class="brand">Sellrise</div>
    <div class="tagline">Интеграционная документация — Retention Intelligence для операторов casino &amp; sportsbook. Приём событий, требования к данным и доставка предсказаний.</div>
  </div>
</header>
<div class="wrap">
<nav class="toc"><div class="toc-title">Разделы</div><ul>{{TOC}}</ul></nav>
<main>{{BODY}}</main>
</div>
<footer>Sellrise · интеграционная документация · конфиденциально, для партнёров по интеграции</footer>
<script>
 (function(){
   var links=[].slice.call(document.querySelectorAll('nav.toc a'));
   var map={}; links.forEach(function(a){map[a.getAttribute('href').slice(1)]=a;});
   var obs=new IntersectionObserver(function(es){
     es.forEach(function(e){
       if(e.isIntersecting){
         links.forEach(function(l){l.classList.remove('active');});
         var a=map[e.target.id]; if(a)a.classList.add('active');
       }
     });
   },{rootMargin:'-12% 0px -78% 0px',threshold:0});
   document.querySelectorAll('main section').forEach(function(s){obs.observe(s);});
 })();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
