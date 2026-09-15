const form = document.querySelector('#mint');
const result = document.querySelector('#result');
const error = document.querySelector('#err');
const seed = document.querySelector('#seed');
const from = document.querySelector('#from');
const to = document.querySelector('#to');
const mine = document.querySelector('#mine');
const mineLink = document.querySelector('#mine-link');
const theirs = document.querySelector('#theirs');
const theirsLink = document.querySelector('#theirs-link');
const mineName = document.querySelector('#mine-name');
const theirsName = document.querySelector('#theirs-name');

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
    mineLink.setAttribute('href', body.links.mine);
    theirs.textContent = body.links.theirs;
    theirsLink.setAttribute('href', body.links.theirs);
    mineName.textContent = body.names.mine || 'your side';
    theirsName.textContent = body.names.theirs || 'their side';
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
  button.addEventListener('click', async () => {
    await navigator.clipboard.writeText(document.querySelector(`#${button.dataset.copy}`).textContent);
    button.textContent = 'Copied';
    setTimeout(() => { button.textContent = 'Copy'; }, 1500);
  });
});
