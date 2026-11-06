/* Opens glossary explanations on hover, focus and tap; Escape or a tap elsewhere closes a tapped one. */
document.documentElement.classList.add('js');

document.addEventListener('DOMContentLoaded', function () {
  var main = document.getElementById('main');
  var pinned = null; // button whose explanation was opened by click or tap
  var current = null;

  function tipFor(btn) { return document.getElementById(btn.getAttribute('aria-describedby')); }

  function hideTip(btn) {
    tipFor(btn).hidden = true;
    if (current === btn) current = null;
  }

  function hideAll() {
    if (current) hideTip(current);
    pinned = null;
  }

  function show(btn) {
    if (current && current !== btn) hideTip(current);
    var tip = tipFor(btn);
    tip.hidden = false;
    var m = main.getBoundingClientRect();
    var b = btn.getBoundingClientRect();
    tip.style.top = (b.bottom - m.top + 6) + 'px';
    var left = b.left - m.left;
    var max = m.width - tip.offsetWidth - 8;
    tip.style.left = Math.max(8, Math.min(left, max)) + 'px';
    current = btn;
  }

  // The whole-map drawing is open without JavaScript; on a narrow screen it starts closed, the lists come first.
  var whole = document.querySelector('details.map-whole');
  if (whole && window.matchMedia && window.matchMedia('(max-width: 40em)').matches) whole.open = false;

  // Chain highlighting in the whole-map drawing: pointing at or focusing a box dims everything not on its chain
  // (the sets are computed at build time and written as data-chain / data-chain-links). A first tap on a touch screen
  // shows the chain and keeps it; a second tap on the same box follows its link. Escape or a tap elsewhere clears.
  var drawing = document.querySelector('.map-whole svg.map-svg');
  if (drawing) {
    var pinnedNode = null;
    var lastPointer = 'mouse';
    var setChain = function (node) {
      var nodes = (node.getAttribute('data-chain') || '').split(' ');
      var links = (node.getAttribute('data-chain-links') || '').split(' ');
      drawing.classList.add('is-focusing');
      drawing.querySelectorAll('.node').forEach(function (n) {
        n.classList.toggle('on-chain', nodes.indexOf(n.getAttribute('data-key')) >= 0);
      });
      drawing.querySelectorAll('.link').forEach(function (l) {
        l.classList.toggle('on-chain', links.indexOf(l.getAttribute('data-link')) >= 0);
      });
    };
    var clearChain = function () {
      drawing.classList.remove('is-focusing');
      drawing.querySelectorAll('.on-chain').forEach(function (n) { n.classList.remove('on-chain'); });
    };
    var restore = function () { if (pinnedNode) setChain(pinnedNode); else clearChain(); };
    // leaving a box keeps the chain (no flicker in the gaps); it changes on entering another box and clears when
    // the pointer leaves the whole drawing
    drawing.addEventListener('mouseleave', restore);
    drawing.querySelectorAll('.node[data-chain]').forEach(function (node) {
      node.addEventListener('mouseenter', function () { setChain(node); });
      node.addEventListener('focusin', function () { setChain(node); });
      node.addEventListener('focusout', restore);
      node.addEventListener('pointerdown', function (e) { lastPointer = e.pointerType || 'mouse'; });
      node.addEventListener('click', function (e) {
        if (lastPointer === 'touch' && pinnedNode !== node) {
          e.preventDefault();
          pinnedNode = node;
          setChain(node);
        }
      });
    });
    document.addEventListener('click', function (e) {
      if (!e.target.closest || !e.target.closest('.map-whole svg .node')) { pinnedNode = null; clearChain(); }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { pinnedNode = null; clearChain(); }
    });
  }

  document.querySelectorAll('.tip').forEach(function (t) { t.hidden = true; });

  document.querySelectorAll('.term').forEach(function (btn) {
    btn.addEventListener('mouseenter', function () { show(btn); });
    btn.addEventListener('mouseleave', function () {
      if (pinned !== btn && document.activeElement !== btn) hideTip(btn);
    });
    btn.addEventListener('focus', function () { show(btn); });
    btn.addEventListener('blur', function () { if (pinned !== btn) hideTip(btn); });
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (pinned === btn) { hideAll(); } else { pinned = btn; show(btn); }
    });
  });

  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hideAll(); });
  document.addEventListener('click', function () { hideAll(); });
});
