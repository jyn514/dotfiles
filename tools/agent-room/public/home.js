const form = document.querySelector('#mint');
const result = document.querySelector('#result');
const error = document.querySelector('#err');
const seed = document.querySelector('#seed');
const from = document.querySelector('#from');
const to = document.querySelector('#to');
const mine = document.querySelector('#mine');
const theirs = document.querySelector('#theirs');

form.addEventListener('submit', async event => {
  event.preventDefault();
  error.textContent = '';
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch('/api/rooms', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ seed: seed.value, from: from.value, to: to.value })
    });
    const body = await response.json();
    if (!response.ok) throw Error(body.error);
    mine.textContent = body.links.mine;
    theirs.textContent = body.links.theirs;
    form.hidden = true;
    result.hidden = false;
  } catch (caught) {
    error.textContent = caught.message;
  } finally {
    button.disabled = false;
  }
});

document.querySelector('#again').addEventListener('click', () => {
  result.hidden = true;
  form.hidden = false;
});

document.querySelectorAll('[data-copy]').forEach(button => {
  button.addEventListener('click', () => navigator.clipboard.writeText(document.querySelector(`#${button.dataset.copy}`).textContent));
});
