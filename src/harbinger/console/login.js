const form = document.getElementById('login-form');
form.addEventListener('submit', async event => {
  event.preventDefault();
  const message = document.getElementById('login-error');
  message.textContent = '';
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const fields = new FormData(form);
    const response = await fetch('/auth/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: fields.get('username'), password: fields.get('password')})
    });
    form.elements.password.value = '';
    if (!response.ok) throw new Error(response.status === 429 ? '잠시 후 다시 시도하세요.' : '로그인 정보를 확인하세요.');
    sessionStorage.removeItem('harbinger:review:synthetic-example');
    location.replace('/console/');
  } catch (error) {
    message.textContent = error.message;
  } finally { button.disabled = false; }
});
