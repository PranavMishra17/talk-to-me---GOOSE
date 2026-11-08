"""Build the public GitHub Pages site into docs/ from the real landing page and personality files. No backend needed.
  uv run python scripts/site.py
The live app stays web/static/index.html; this swaps its backend calls for the idea, screenshots and setup steps.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from proxy_core.personality import cards

REPO = "https://github.com/PranavMishra17/talk-to-me---GOOSE"

CSS = """
  .section{margin:0 0 56px}
  .section h2{font-size:38px;margin:0 0 4px}
  .section .lead{margin:0 0 18px;max-width:64ch;color:var(--mute)}
  .shots{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  .shot{margin:0;border:3px solid var(--ink);box-shadow:var(--shadow);background:var(--paper)}
  .shot img{display:block;width:100%;height:auto;border-bottom:3px solid var(--ink)}
  .shot figcaption{padding:10px 12px;font-size:14px}
  .shot figcaption b{display:block;font-family:Bangers;font-size:20px;letter-spacing:.04em;font-weight:400}
  .rules{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
  .rule{border:3px solid var(--ink);box-shadow:var(--shadow);padding:14px 16px;background:var(--paper)}
  .rule h3{font-family:Bangers;font-weight:400;font-size:22px;letter-spacing:.04em;margin:0 0 6px}
  .rule p{margin:0;font-size:14px}
  .steps{border:3px solid var(--ink);box-shadow:var(--shadow);padding:20px;background:var(--paper);counter-reset:s}
  .steps ol{margin:0;padding:0;list-style:none;display:grid;gap:16px}
  .steps li{display:grid;grid-template-columns:34px minmax(0,1fr);gap:10px}
  .steps li:before{counter-increment:s;content:counter(s);font-family:Bangers;font-size:24px;line-height:1.1;background:var(--balloon);color:#1A1423;border:2px solid #1A1423;text-align:center;height:32px}
  .steps h3{margin:0 0 4px;font-size:16px}
  .steps p{margin:0 0 6px}
  pre{margin:6px 0 0;padding:10px 12px;border:2px solid var(--ink);background:color-mix(in oklab,var(--ink) 6%,var(--paper));overflow-x:auto;font:13px/1.5 ui-monospace,Consolas,monospace}
  .steps a,.section a{color:inherit;text-decoration-thickness:2px;text-underline-offset:3px}
  .github{display:inline-block;margin-top:18px}
  @media (max-width:860px){.shots,.rules{grid-template-columns:1fr}}
"""

SECTIONS = f"""  <section class="section" id="app">
    <h2 class="shout">The app.</h2>
    <p class="lead">One place for everything Goose did while you were away, and one button to talk to it yourself. These screenshots use the mock data that ships with the repo.</p>
    <div class="shots">
      <figure class="shot"><img src="screens/app.png" alt="Home screen with call history, the calendar and the Talk to me, Goose button" loading="lazy"><figcaption><b>Your home screen</b>Every call with a one-line summary and what needs you. Press the egg to talk to Goose.</figcaption></figure>
      <figure class="shot"><img src="screens/call.png" alt="A saved call with summary, actions and full transcript" loading="lazy"><figcaption><b>Every call, saved</b>Summary, outcome, actions and the full transcript.</figcaption></figure>
      <figure class="shot"><img src="screens/room.png" alt="Live room view with the caller's tier and a pending confirmation" loading="lazy"><figcaption><b>A live call</b>Who's calling, their tier, and when Goose is waiting for a yes. Hold to talk works in a loud room.</figcaption></figure>
      <figure class="shot"><img src="screens/data.png" alt="Mock email, Slack and calendar data, each row tagged with its privacy tier" loading="lazy"><figcaption><b>What Goose may share</b>Every record carries a tier. Code filters by it, so the model never sees more than the caller may hear.</figcaption></figure>
    </div>
  </section>

  <section class="section" id="how">
    <h2 class="shout">How it works.</h2>
    <p class="lead">Each rule came from watching a real call go wrong.</p>
    <div class="rules">
      <div class="rule"><h3>Code decides</h3><p>Fast models skip tools and invent actions. Anything that must happen, from the caller's tier to the goodbye, is enforced in code. The prompt only sets the manners.</p></div>
      <div class="rule"><h3>Privacy is a filter</h3><p>Records are public, friends, family or private. A stranger asking for your calendar gets busy blocks, because the titles were never in the prompt.</p></div>
      <div class="rule"><h3>Context first</h3><p>A known caller's emails, Slack threads, tasks and your free time are pulled before hello, so the first answer needs no lookup.</p></div>
      <div class="rule"><h3>Asks before acting</h3><p>Messages, bookings and summons wait for a spoken yes, in one short human question, never a read-back of arguments.</p></div>
      <div class="rule"><h3>Holds its ground</h3><p>Interruptions, silence, injection and "I'm his boss" change nothing. After three real violations it hangs up in its own words.</p></div>
      <div class="rule"><h3>One line per model</h3><p>STT, LLM, TTS and turn detection are config lines, chosen by measured A/B. Personalities plug into any agent.</p></div>
    </div>
  </section>

  <section class="section" id="setup">
    <h2 class="shout">Set it up.</h2>
    <p class="lead">Open source, Python, about five minutes. You need <a href="https://docs.astral.sh/uv/getting-started/installation/">uv</a> and a free <a href="https://cloud.livekit.io">LiveKit Cloud</a> project.</p>
    <div class="steps"><ol>
      <li><div><h3>Clone and install</h3><p>The tests need no keys and spend nothing.</p>
<pre>git clone {REPO}.git
cd talk-to-me---GOOSE
uv sync
uv run pytest -q</pre></div></li>
      <li><div><h3>Look around with no keys</h3><p>Fake data, no agent. Then open http://localhost:8000.</p>
<pre>GOOSE_MOCK=1 uv run uvicorn app.api:app --port 8000</pre></div></li>
      <li><div><h3>Add your keys</h3><p>Copy the sample, fill in the three LiveKit values, then check them.</p>
<pre>cp .env.sample .env
uv run python scripts/check_env.py</pre></div></li>
      <li><div><h3>Talk to it</h3><p>Pick who's calling and type, in the terminal:</p>
<pre>uv run python scripts/call.py</pre><p>Or run every agent and the web app together, then open http://localhost:8000:</p>
<pre>uv run python scripts/stage.py up</pre></div></li>
      <li><div><h3>Give it a phone number</h3><p>Rent a number in your LiveKit project, create a dispatch rule from <code>dispatch-rule.json</code>, assign it to the number, and call.</p></div></li>
    </ol></div>
    <a class="cta github" href="{REPO}">Get the code on GitHub</a>
  </section>
"""


def sub(s, a, b):
    assert a in s, a
    return s.replace(a, b, 1)


def build() -> str:
    s = (ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
    s = sub(s, "</style>", CSS + "</style>")
    s = re.sub(r'<div class="links">.*?</div>\n', '<div class="links"><nav><a href="#cast">Stand-ins</a><a href="#app">The app</a>'
               '<a href="#how">How it works</a><a href="#setup">Set it up</a></nav>'
               f'<a href="{REPO}">GitHub</a></div>\n', s, count=1, flags=re.S)
    s = sub(s, 'href="/app?talk=1">', 'href="#setup">')
    s = sub(s, '<a class="cta" href="#room">Call Goose</a>', '<a class="cta" href="#setup">Get Goose</a>')
    s = re.sub(r'\s*<div class="phone" id="phone">.*?</div>', '\n      <div class="phone">Open source<small>Runs on your own LiveKit project and phone number</small></div>',
               s, count=1, flags=re.S)
    s = re.sub(r'  <section class="room" id="room">.*?</section>\n', SECTIONS, s, count=1, flags=re.S)
    s = sub(s, "</footer>", f' <a href="{REPO}">Source on GitHub</a>.</footer>')
    s = re.sub(r"let packs=\[.*?\n\];", "let packs=" + json.dumps(cards(), ensure_ascii=False) + ";", s, count=1, flags=re.S)
    s = s.replace(",sel=document.getElementById('packsel')", "")
    s = s.replace("\n  const o=document.createElement('option');o.value=p.id;o.textContent=p.name;sel.appendChild(o);", "")
    s = s.replace("\n  sel.value=id;", "")
    s = re.sub(r"// personalities/\*\.yaml are the source.*?\nrender\(\);\n.*?</script>", "render();\n</script>", s, count=1, flags=re.S)
    for gone in ("fetch(", "packsel", "roomform", "/rooms", "href=\"/app"):
        assert gone not in s, gone
    return s


if __name__ == "__main__":
    (ROOT / "docs" / "index.html").write_text(build(), encoding="utf-8")
    (ROOT / "docs" / ".nojekyll").write_text("", encoding="utf-8")
    print("wrote docs/index.html")
