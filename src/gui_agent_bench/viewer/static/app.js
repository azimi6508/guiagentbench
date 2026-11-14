import('/js/main.js').catch(() => {
  const app = document.getElementById('app');
  app.textContent = '';
  const box = document.createElement('div');
  box.className = 'page-error';
  const title = document.createElement('h2');
  title.textContent = 'The viewer could not load';
  const text = document.createElement('p');
  text.textContent = 'Reload this page. If the problem continues, restart the viewer with:';
  const command = document.createElement('pre');
  command.className = 'code';
  command.textContent = 'python scripts/view.py [runs-directory] --port 8080';
  box.append(title, text, command);
  app.append(box);
});
