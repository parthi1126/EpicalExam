document.addEventListener('DOMContentLoaded', function () {
  const checkbox = document.getElementById('agreeCheckbox');
  const startBtn = document.getElementById('startExamBtn');
  const countdownOverlay = document.getElementById('countdownOverlay');
  const countdownElement = document.getElementById('countdown');
  const examUrl = startBtn.getAttribute('data-exam-url');

  checkbox.addEventListener('change', function () {
    startBtn.disabled = !this.checked;
  });

  startBtn.addEventListener('click', function () {
    countdownOverlay.style.display = 'flex';
    let countdown = 10;
    countdownElement.textContent = countdown;

    const interval = setInterval(() => {
      countdown--;
      countdownElement.textContent = countdown;

      if (countdown <= 0) {
        clearInterval(interval);
        window.location.href = examUrl;
      }
    }, 1000);
  });
});
