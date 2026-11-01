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
