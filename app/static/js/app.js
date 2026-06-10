document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-progress-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector("button[type='submit']");
      const panel = document.querySelector("[data-progress-panel]");
      const text = document.querySelector("[data-progress-text]");
      if (button) {
        button.disabled = true;
        button.textContent = button.dataset.busyText || "处理中...";
      }
      if (panel) panel.hidden = false;
      const customStages = form.dataset.progressStages;
      const stages = customStages ? customStages.split("|") : [
        "检查状态门禁",
        "构建施工包",
        "调用模型或内部服务",
        "写入数据库状态",
        "刷新页面"
      ];
      let index = 0;
      if (text) text.textContent = stages[index];
      window.setInterval(() => {
        index = Math.min(index + 1, stages.length - 1);
        if (text) text.textContent = stages[index];
      }, 1100);
    });
  });
});
