// Na TV não há console: erros de script, e o navegador de cada aparelho novo, vão para o log do servidor.
// Script comum (não módulo) e em ES5, carregado antes de tudo: avisa até quando um navegador velho não lê o resto
(function () {
  function report(msg) {
    try {
      var x = new XMLHttpRequest();
      x.open("POST", "/api/log");
      x.setRequestHeader("Content-Type", "application/json");
      x.send(JSON.stringify({ msg: msg.slice(0, 140) + " | " + navigator.userAgent }));
    } catch (e) {}
  }
  window.addEventListener("error", function (e) {
    if (e.message) report("erro de script: " + e.message + " em " + String(e.filename).split("/").pop() + ":" + e.lineno);
  });
  try {
    if (localStorage.getItem("iptv.browser") !== navigator.userAgent) {
      report("aparelho novo em " + location.pathname);
      localStorage.setItem("iptv.browser", navigator.userAgent);
    }
  } catch (e) {}
})();
