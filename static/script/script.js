document.getElementById('loginForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  const email = document.getElementById('email').value.toLowerCase();
  const password = document.getElementById('password').value;

  if (!email.endsWith('@gmail.com')) {
    alert("Only Gmail addresses are allowed");
    return;
  }

  try {
    if ((email === 'r.vinith777@gmail.com')&&(password=='qwer1234')) {
      window.location.href = 'instruction.html'; // or any page you want
    } else {
      alert(`Invalid email or password`);
    }
  } catch (err) {
    console.error(err);
    alert("Login failed");
  }
});