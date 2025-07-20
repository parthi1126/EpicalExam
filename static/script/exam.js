document.addEventListener("DOMContentLoaded", function () {
    // State variables
    const state = {
        examStarted: false,
        switchCount: 0,
        timer: 60 * 90, // 90 minutes in seconds
        countdownInterval: null,
        examStartTime: null,
        testId: "TEST01",
        gracePeriod: 5 // seconds
    };

    // DOM elements
    const elements = {
        terminationOverlay: document.getElementById('termination-overlay'),
        countdownElement: document.getElementById("time"),
        controls: document.getElementById('controls'),
        footer: document.querySelector('footer')
    };

    // Initialize UI
    function initUI() {
        elements.terminationOverlay.classList.add('hidden');
        elements.controls.style.display = 'none';
        updateTimerDisplay();
    }

    // Security: Prevent keyboard shortcuts
    function setupSecurity() {
        document.addEventListener('keydown', function (e) {
            // Block common shortcuts
            if ((e.ctrlKey || e.metaKey) && ['c', 'v', 'x', 'a', 's', 'p', 'u'].includes(e.key.toLowerCase())) {
                e.preventDefault();
            }
            // Block F12 (dev tools)
            if (e.key === 'F12') e.preventDefault();
        });

        // Prevent clipboard and context menu operations
        ["copy", "paste", "cut", "contextmenu"].forEach(evt => {
            document.addEventListener(evt, (e) => e.preventDefault());
        });
    }

    // Handle visibility changes (tab switching)
    function handleVisibilityChange() {
        if (!state.examStarted) return;

        const now = Date.now();
        const secondsSinceStart = (now - state.examStartTime) / 1000;

        // Ignore during grace period
        if (secondsSinceStart < state.gracePeriod) {
            console.log("⚠️ Ignoring visibility change during grace period.");
            return;
        }

        if (document.hidden) {
            state.switchCount++;
            if (state.switchCount <= 3) {
                alert(`⚠️ Warning ${state.switchCount}/3: Please stay on the exam tab.`);
            } else {
                terminateExam("Exceeded allowed tab switches (3)");
            }
        }
    }

    // Update timer display
    function updateTimerDisplay() {
        const minutes = Math.floor(state.timer / 60);
        const seconds = state.timer % 60;
        elements.countdownElement.textContent = 
            `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;

        if (state.timer <= 0) {
            terminateExam("⏰ Time's up! Exam submitted automatically.");
        }
    }

    // Timer countdown function
    function updateTimer() {
        state.timer--;
        updateTimerDisplay();
    }

    // Start the exam
    window.startExam = function () {
        if (state.examStarted) return;

        function beginExam() {
            state.examStarted = true;
            state.examStartTime = Date.now();
            state.countdownInterval = setInterval(updateTimer, 1000);

            elements.footer.style.display = 'none';
            elements.controls.style.display = 'block';

            loadQuestion(1);
        }

        // Request fullscreen first
        const docEl = document.documentElement;
        if (docEl.requestFullscreen) {
            docEl.requestFullscreen()
                .then(() => {
                    // Small delay to ensure browser focus
                    setTimeout(beginExam, 1000);
                })
                .catch(err => {
                    console.error("Fullscreen failed:", err);
                    alert("⚠️ Fullscreen failed. Please allow fullscreen to begin the exam.");
                });
        } else {
            // Fallback without fullscreen (not recommended)
            beginExam();
        }
    };

    // Terminate the exam
    function terminateExam(reason = "Exam terminated") {
        // Clear intervals and exit fullscreen
        clearInterval(state.countdownInterval);
        if (document.fullscreenElement) {
            document.exitFullscreen().catch(console.error);
        }

        // Show termination overlay
        const overlay = elements.terminationOverlay;
        overlay.querySelector('h2').textContent = '❌ Exam Terminated';
        overlay.querySelector('p').textContent = reason;
        overlay.classList.remove('hidden');

        // Send termination to server
        fetch("/submit_answer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                test_id: state.testId,
                qid: "terminated",
                selected_answers: [],
                status: "terminated"
            })
        }).catch(console.error);

        // Redirect after delay
        setTimeout(() => {
            window.location.href = "/logout";
        }, 5000);
    }

    // Load a question
    function loadQuestion(qNumber) {
        console.log("Loading question:", qNumber);
        // Implementation would go here
    }

    // Event listeners
    document.addEventListener("visibilitychange", handleVisibilityChange);

    // Initialize
    initUI();
    setupSecurity();
});