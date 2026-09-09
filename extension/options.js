// Settings: which CRM admin origins the Run button is injected into.
//
// The CRM's hostname is deployment-specific (DEPLOY.md leaves it as
// your-domain.com), so it cannot be baked into the manifest. Origins are added
// here, Chrome prompts for the host permission, and the content script is
// registered for exactly the granted set — nothing broader.

import { getOrigins, syncRegistration, ORIGINS_KEY } from './registration.js';

const $ = (id) => document.getElementById(id);

const say = (text, bad) => {
  $('msg').textContent = text;
  $('msg').style.color = bad ? '#dc2626' : '';
};

async function render() {
  const origins = await getOrigins();
  const ul = $('origins');
  ul.textContent = '';

  for (const match of origins) {
    const held = await chrome.permissions.contains({ origins: [match] });

    const li = document.createElement('li');
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = match;

    const pill = document.createElement('span');
    pill.className = 'pill ' + (held ? 'ok' : 'warn');
    pill.textContent = held ? 'allowed' : 'not allowed';

    const li_buttons = [];
    if (!held) {
      const grant = document.createElement('button');
      grant.className = 'primary';
      grant.textContent = 'Allow';
      grant.addEventListener('click', async () => {
        // Must be called from a user gesture, so it lives on the button.
        const ok = await chrome.permissions.request({ origins: [match] });
        if (!ok) return say('Chrome declined that permission.', true);
        await syncRegistration();
        say('Allowed. Reload the CRM tab to see the Run button.');
        render();
      });
      li_buttons.push(grant);
    }

    const drop = document.createElement('button');
    drop.textContent = 'Remove';
    drop.addEventListener('click', async () => {
      const next = (await getOrigins()).filter((o) => o !== match);
      await chrome.storage.local.set({ [ORIGINS_KEY]: next });
      // Give the permission back too, so removing really removes.
      await chrome.permissions.remove({ origins: [match] }).catch(() => {});
      await syncRegistration();
      render();
    });
    li_buttons.push(drop);

    li.append(name, pill, ...li_buttons);
    ul.append(li);
  }
}

$('add').addEventListener('click', async () => {
  const raw = $('origin').value.trim();
  if (!raw) return;
  // chrome.permissions wants a match pattern, and a bare origin is the mistake
  // everyone makes — fix it rather than rejecting it.
  const match = /\*$|\/$/.test(raw) ? raw.replace(/\/$/, '/*') : raw + '/*';
  try {
    new URL(match.replace(/\*$/, ''));
  } catch (e) {
    return say(`Not a URL: ${raw}`, true);
  }

  // request() must run inside the user gesture, so nothing may be awaited
  // before it. Chrome is a no-op for a permission already held.
  const ok = await chrome.permissions.request({ origins: [match] });
  if (!ok) return say('Chrome declined that permission.', true);

  const origins = await getOrigins();
  if (origins.includes(match)) return say('Already listed.');

  await chrome.storage.local.set({ [ORIGINS_KEY]: [...origins, match] });
  await syncRegistration();
  $('origin').value = '';
  say(`Added ${match}. Reload the CRM tab to see the Run button.`);
  render();
});

syncRegistration().then(render);
