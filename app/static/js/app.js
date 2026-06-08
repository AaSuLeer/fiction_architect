document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".pipeline-form").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector("button[type='submit']");
      const progress = form.querySelector(".pipeline-progress");
      const text = form.querySelector(".pipeline-text");
      if (button) {
        button.disabled = true;
        button.textContent = "管道运行中...";
      }
      if (progress) progress.classList.add("active");
      const stages = ["作者部门生成写作任务书", "连续性工作室准备资料", "写作部门生成正文", "编辑部门审稿", "连续性工作室写回候选"];
      let index = 0;
      if (text) text.textContent = stages[index];
      window.setInterval(() => {
        index = Math.min(index + 1, stages.length - 1);
        if (text) text.textContent = stages[index];
      }, 900);
    });
  });
});
