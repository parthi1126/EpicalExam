document.addEventListener("DOMContentLoaded", function () {
  let examStarted = false;
  let switchCount = 0;
  let timer = 60 * 90;
  let countdownInterval = null;
  let examStartTime = null;

  const testId = "TEST01";
  const terminationOverlay = document.getElementById('termination-overlay');
  const countdownElement = document.getElementById("time");

  terminationOverlay.classList.add('hidden');

  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && ['c', 'v', 'x', 'a', 's', 'p', 'u'].includes(e.key.toLowerCase())) {
      e.preventDefault();
    }
    if (e.key === 'F12') e.preventDefault();
  });

  ["copy", "paste", "cut", "contextmenu"].forEach(evt =>
    document.addEventListener(evt, (e) => e.preventDefault())
  );

  // Visibility change – termination logic
  document.addEventListener("visibilitychange", () => {
    if (!examStarted) return;

    const now = Date.now();
    const secondsSinceStart = (now - examStartTime) / 1000;

    if (secondsSinceStart < 5) {
      console.log("⚠️ Ignoring visibility change during grace period.");
      return;
    }

    if (document.hidden) {
      switchCount++;
      if (switchCount <= 3) {
        alert(`⚠️ Warning ${switchCount}/3: Please stay on the exam tab.`);
      } else {
        terminateExam("Exceeded allowed tab switches (3)");
      }
    }
  });

  function updateTimer() {
    const minutes = Math.floor(timer / 60);
    const seconds = timer % 60;
    countdownElement.textContent = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;

    if (timer <= 0) {
      terminateExam("⏰ Time's up! Exam submitted automatically.");
    }

    timer--;
  }

window.startExam = function () {
  if (examStarted) return;

  // Delay start until fullscreen is confirmed
  function beginExamAfterFullscreen() {
    // Now begin
    examStarted = true;
    examStartTime = Date.now(); // Start time
    countdownInterval = setInterval(updateTimer, 1000);

    document.querySelector('footer').style.display = 'none';
    document.getElementById('controls').style.display = 'block';

    loadQuestion(1);
  }

  // Request fullscreen, then wait for event
  const docEl = document.documentElement;
  if (docEl.requestFullscreen) {
    docEl.requestFullscreen().then(() => {
      // Wait 1 second to ensure browser focus
      setTimeout(beginExamAfterFullscreen, 1000);
    }).catch(err => {
      console.error("Fullscreen failed", err);
      alert("⚠️ Fullscreen failed. Please allow fullscreen to begin the exam.");
    });
  } else {
    // Fallback: start immediately (not recommended)
    beginExamAfterFullscreen();
  }
};


  function terminateExam(reason = "Exam terminated") {
    if (countdownInterval) clearInterval(countdownInterval);
    if (document.fullscreenElement) document.exitFullscreen();

    terminationOverlay.querySelector('.overlay-message h2').textContent = '❌ Exam Terminated';
    terminationOverlay.querySelector('.overlay-message p').textContent = reason;
    terminationOverlay.classList.remove('hidden');

    fetch("/submit_answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        test_id: testId,
        qid: "terminated",
        selected_answers: [],
        status: "terminated"
      })
    }).catch(console.error);

    setTimeout(() => window.location.href = "/logout", 5000);
  }

  function loadQuestion(qNumber) {
    console.log("📘 Load Question:", qNumber);
  }

  updateTimer();
  document.getElementById('controls').style.display = 'none';
});