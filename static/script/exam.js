document.addEventListener("DOMContentLoaded", function () {
  // Request fullscreen
  if (document.documentElement.requestFullscreen) {
    document.documentElement.requestFullscreen();
  }

  let switchCount = 0;
  let timer = 60 * 90; // 90 minutes

  const testId = "TEST01"; // Replace dynamically if needed
  const terminationOverlay = document.getElementById('termination-overlay');
  const countdownElement = document.getElementById("time");

  // Restrict keys
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && ['c', 'v', 'x', 'a', 's', 'p', 'u'].includes(e.key.toLowerCase())) {
      e.preventDefault();
    }
    if (e.key === 'F12') e.preventDefault();
  });

  // Block mouse actions
  ["copy", "paste", "cut", "contextmenu"].forEach(evt =>
    document.addEventListener(evt, (e) => e.preventDefault())
  );

  // Detect tab switch
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      switchCount++;
      if (switchCount <= 2) {
        alert(`⚠️ Tab switch detected (${switchCount}/2 allowed). One more and your exam will be terminated.`);
      } else {
        terminateExam();
      }
    }
  });

  // Timer
  function updateTimer() {
    const minutes = Math.floor(timer / 60);
    const seconds = timer % 60;
    countdownElement.textContent = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    if (timer <= 0) {
      terminateExam();
    }
    timer--;
  }
  const countdownInterval = setInterval(updateTimer, 1000);

  // Manual submit
  document.getElementById("submit-btn").addEventListener("click", function () {
    if (confirm("Are you sure you want to submit the exam?")) {
      alert("✅ Submitted!");
      window.location.href = "/logout";
    }
  });

  // Termination logic
  function terminateExam() {
    clearInterval(countdownInterval);
    terminationOverlay.classList.remove('hidden');
    sendTerminationStatus();
    setTimeout(() => window.location.href = "/logout", 3000);
  }

  function sendTerminationStatus() {
    fetch("/submit_answer", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        test_id: testId,
        qid: "terminated",
        selected_answers: [],
        status: "terminated"
      })
    }).catch(err => console.error("Termination error:", err));
  }
});
