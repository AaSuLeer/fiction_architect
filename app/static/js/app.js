document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-progress-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector("button[type='submit']");
      const panel = document.querySelector("[data-progress-panel]");
      const text = document.querySelector("[data-progress-text]");
      if (button) {
        button.disabled = true;
        button.textContent = "正在生成...";
      }
      if (panel) panel.hidden = false;
      const customStages = form.dataset.progressStages;
      const stages = customStages ? customStages.split("|") : [
        "整理本章写作任务",
        "检索连续性资料",
        "调用大模型写作",
        "编辑审核与自动重写",
        "等待人工确认正文"
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
