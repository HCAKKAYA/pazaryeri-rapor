// Seçilen temayı sayfa çizilmeden önce uygular (yanıp sönmeyi önler). Seçim yoksa sistem teması.
(function () {
  try {
    var t = localStorage.getItem('panel-tema');
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
  } catch (e) { /* depolama kapalıysa sistem teması */ }
})();
