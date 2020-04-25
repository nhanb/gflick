window.addEventListener("DOMContentLoaded", function (event) {
  // Don't do anything if these 2 vars aren't populated:
  if (!username || !password) {
    return;
  }
  let authPrefix =
    window.location.protocol +
    "//" +
    username +
    ":" +
    password +
    "@" +
    window.location.host;

  Array.from(document.querySelectorAll("a"))
    .filter(function (el) {
      return el.getAttribute("href").startsWith("/v/");
    })
    .forEach(function (el) {
      let href = el.getAttribute("href");
      el.setAttribute("href", authPrefix + href);
    });
});
