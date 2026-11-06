// How the person talks to the agent: hold to talk, type, or open mic. Shared by the room page and /app.
const KEY = 'goose-input';
const MODES = [['hold', 'Hold to talk'], ['type', 'Type'], ['open', 'Open mic']];
const MIC = {echoCancellation: true, noiseSuppression: true, autoGainControl: true};

const CSS = `
  .gi{display:grid;gap:12px;margin-top:14px;width:100%;color:#1A1423;font-family:"Atkinson Hyperlegible",system-ui,sans-serif}
  .gi-modes{display:flex;flex-wrap:wrap;gap:8px;border:0;margin:0;padding:0}
  .gi-modes legend{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
  .gi-modes input{position:absolute;opacity:0}
  .gi-modes span{display:block;padding:4px 12px;border:2px solid #1A1423;background:#FFF8E7;font-weight:700;font-size:16px;cursor:pointer}
  .gi-modes input:checked+span{background:#4CC9F0}
  .gi-modes input:focus-visible+span{outline:3px solid #4CC9F0;outline-offset:3px}
  .gi-hold{width:100%;padding:10px 16px;touch-action:none;user-select:none;-webkit-user-select:none;cursor:pointer;background:#E63946;color:#fff;border:3px solid #1A1423;box-shadow:5px 5px 0 #1A1423;font:400 26px/1.1 Bangers,Impact,sans-serif;letter-spacing:.03em;transition:transform .12s ease-out,box-shadow .12s ease-out}
  .gi-hold.on{background:#4CC9F0;color:#1A1423;transform:translate(5px,5px);box-shadow:0 0 0 #1A1423}
  .gi-hold:focus-visible{outline:3px solid #4CC9F0;outline-offset:3px}
  .gi-hold[disabled]{opacity:.6;cursor:default}
  .gi-type{display:flex;gap:10px}
  .gi-type input{flex:1;min-width:0;padding:8px 12px;border:3px solid #1A1423;background:#FFF8E7;color:#1A1423;font:inherit;font-size:18px}
  .gi-type input:focus-visible{outline:3px solid #4CC9F0;outline-offset:2px}
  .gi-type button{padding:0 22px;cursor:pointer;background:#E63946;color:#fff;border:3px solid #1A1423;box-shadow:5px 5px 0 #1A1423;font:400 22px Bangers,Impact,sans-serif;letter-spacing:.03em}
  .gi-open,.gi-note{margin:0;padding:8px 14px;border:3px solid #1A1423;background:#FFD23F;font-weight:700;font-size:18px}
  .gi-note{background:#FFF8E7}
  .gi-tap{position:fixed;left:16px;right:16px;bottom:16px;z-index:9;padding:14px;cursor:pointer;background:#FFD23F;color:#1A1423;border:3px solid #1A1423;box-shadow:5px 5px 0 #1A1423;font:400 32px/1 Bangers,Impact,sans-serif;letter-spacing:.03em}
  .gi-tap:focus-visible{outline:3px solid #4CC9F0;outline-offset:3px}
  [hidden]{display:none!important}
  @media (prefers-reduced-motion: reduce){.gi-hold{transition:none}}
`;

export function savedMode() {
  try { const m = localStorage.getItem(KEY); return MODES.some(([id]) => id === m) ? m : 'hold'; } catch { return 'hold'; }
}

// `onLine(text)` shows a typed line in the transcript. attach() takes what liveInput or a mock returns.
export function inputBar(host, onLine) {
  if (!document.getElementById('gi-css')) document.head.append(Object.assign(document.createElement('style'), {id: 'gi-css', textContent: CSS}));
  host.innerHTML = `<div class="gi">
    <fieldset class="gi-modes"><legend>How you talk to the agent</legend>${MODES.map(([id, label]) =>
      `<label><input type="radio" name="gi-mode" value="${id}"><span>${label}</span></label>`).join('')}</fieldset>
    <p class="gi-note" hidden></p>
    <button type="button" class="gi-hold" disabled>Hold to talk (or hold Space)</button>
    <form class="gi-type"><input aria-label="Type what you want to say" placeholder="Type what you want to say" autocomplete="off" disabled><button disabled>Send</button></form>
    <p class="gi-open">Mic is open.</p>
  </div>`;
  const $ = s => host.querySelector(s);
  const hold = $('.gi-hold'), form = $('.gi-type'), box = form.querySelector('input'), send = form.querySelector('button');
  let mode = savedMode(), input = null, held = false;

  function show() {
    host.querySelectorAll('[name=gi-mode]').forEach(r => { r.checked = r.value === mode; });
    hold.hidden = mode !== 'hold';
    form.hidden = mode !== 'type';
    $('.gi-open').hidden = mode !== 'open';
    hold.disabled = !input;
    box.disabled = send.disabled = !input;
    if (input) input.mic(mode === 'open');
  }
  function press() {
    if (!input || held || mode !== 'hold') return;
    held = true;
    hold.classList.add('on');
    hold.textContent = 'Listening. Let go when you finish';
    input.turn(true);
    input.mic(true);
  }
  function release() {
    if (!held) return;
    held = false;
    hold.classList.remove('on');
    hold.textContent = 'Hold to talk (or hold Space)';
    input?.mic(false);
    input?.turn(false);
  }

  host.querySelectorAll('[name=gi-mode]').forEach(r => { r.onchange = () => {
    release();
    mode = r.value;
    try { localStorage.setItem(KEY, mode); } catch {}
    show();
  }; });
  hold.onpointerdown = e => { press(); hold.setPointerCapture(e.pointerId); };
  hold.onpointerup = hold.onpointercancel = hold.onlostpointercapture = release;
  hold.oncontextmenu = e => e.preventDefault();   // a long press on a phone
  form.onsubmit = async e => {
    e.preventDefault();
    const text = box.value.trim();
    if (!text || !input) return;
    box.value = '';
    onLine(text);
    await input.send(text);
  };
  const typing = () => ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
  addEventListener('keydown', e => {
    if (e.code !== 'Space' || mode !== 'hold' || !input || typing()) return;
    e.preventDefault();          // or Space presses whichever button has focus, such as Leave
    document.activeElement?.blur?.();
    if (!e.repeat) press();
  });
  addEventListener('keyup', e => { if (e.code === 'Space') { if (held) e.preventDefault(); release(); } });
  addEventListener('blur', release);
  document.addEventListener('visibilitychange', () => { if (document.hidden) release(); });
  show();

  return {
    attach(next) {
      input = next;
      const none = !next.hasMic;
      $('.gi-note').hidden = !none;
      if (none) { $('.gi-note').textContent = 'No microphone here, so type instead.'; mode = 'type'; }
      show();
    },
    detach() { release(); input = null; $('.gi-note').hidden = true; mode = savedMode(); show(); },
  };
}

// A page that joined without a click on it can have its audio blocked by the browser: one big button unblocks it.
export function audioGate(lk, RoomEvent, assistant) {
  const tap = Object.assign(document.createElement('button'), {className: 'gi-tap', textContent: `Tap to hear ${assistant}`, hidden: true});
  document.body.append(tap);
  const sync = () => { tap.hidden = lk.canPlaybackAudio; };
  tap.onclick = () => lk.startAudio().then(sync, sync);
  lk.on(RoomEvent.AudioPlaybackStatusChanged, sync);
  lk.on(RoomEvent.Disconnected, () => tap.remove());
  lk.startAudio().then(sync, sync);
}

// The real thing. The mic is published muted, so nothing reaches the agent until someone asks for it. A refused mic
// leaves typing working: that is the stage fallback.
export async function liveInput(lk, createLocalAudioTrack) {
  let track = null;
  try {
    track = await createLocalAudioTrack(MIC);
    await track.mute();
    await lk.localParticipant.publishTrack(track);
  } catch { track?.stop(); track = null; }
  const toAgents = method => [...lk.remoteParticipants.values()].filter(p => p.isAgent).forEach(p =>
    lk.localParticipant.performRpc({destinationIdentity: p.identity, method, payload: ''}).catch(() => {}));
  return {
    hasMic: !!track,
    mic(on) { if (on) track?.unmute(); else track?.mute(); },
    turn(on) { toAgents(on ? 'start_turn' : 'end_turn'); },   // muted audio has no silence for VAD to end the turn on
    send: text => lk.localParticipant.sendText(text, {topic: 'lk.chat'}),
  };
}
