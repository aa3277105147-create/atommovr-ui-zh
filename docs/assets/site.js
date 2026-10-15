(() => {
  "use strict";

  // 发布在线计算服务后，只需把这里的占位符替换为公开的 Space 地址。
  const spaceUrl = "__SPACE_URL__";
  const isConfigured = /^https:\/\//.test(spaceUrl) && !spaceUrl.includes("__SPACE_URL__");
  const links = document.querySelectorAll("[data-space-link]");
  const frame = document.querySelector("#space-frame");
  const placeholder = document.querySelector("#space-placeholder");
  const status = document.querySelector("#space-status");

  if (!isConfigured) {
    links.forEach((link) => {
      link.setAttribute("href", "#demo");
      link.removeAttribute("target");
    });
    status.classList.add("is-pending");
    status.lastChild.textContent = " 在线版本正在接入，当前可下载仓库在本机运行";
    return;
  }

  links.forEach((link) => link.setAttribute("href", spaceUrl));
  frame.src = spaceUrl;
  frame.hidden = false;
  placeholder.hidden = true;
})();
