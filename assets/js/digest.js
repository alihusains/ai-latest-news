document.addEventListener('DOMContentLoaded', () => {
  const container = document.querySelector('.digest-container');
  if (!container) return;

  const headings = container.querySelectorAll('h2');
  if (headings.length === 0) return;

  const panels = [];
  const totalItems = { value: 0 };

  headings.forEach((h2, index) => {
    const category = h2.textContent.trim();
    const nextH2 = headings[index + 1];
    const items = [];

    let sibling = h2.nextElementSibling;
    while (sibling && sibling !== nextH2) {
      if (sibling.tagName === 'UL') {
        Array.from(sibling.children).forEach(li => {
          if (li.tagName === 'LI') items.push(li);
        });
      }
      sibling = sibling.nextElementSibling;
    }

    totalItems.value += items.length;
    panels.push({ category, items, count: items.length, index });
  });

  // Hide original rendered content
  const contentWrapper = document.createElement('div');
  contentWrapper.className = 'digest-original';
  contentWrapper.style.display = 'none';
  while (container.firstChild) {
    contentWrapper.appendChild(container.firstChild);
  }
  container.appendChild(contentWrapper);

  // Build tab bar
  const tabNav = document.createElement('nav');
  tabNav.className = 'digest-tabs';
  tabNav.setAttribute('aria-label', 'Digest categories');

  const tabList = document.createElement('ul');
  tabList.className = 'digest-tab-list';

  const tabs = [];

  const makeTabButton = (id, label, count) => {
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.className = 'digest-tab';
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-selected', 'false');
    btn.dataset.tab = id;
    btn.innerHTML = `${label} <span class="digest-badge">${count}</span>`;
    li.appendChild(btn);
    tabList.appendChild(li);
    tabs.push({ id, button: btn });
    return btn;
  };

  makeTabButton('glance', '⚡ At a Glance', totalItems.value);

  panels.forEach(panel => {
    makeTabButton(String(panel.index), panel.category, panel.count);
  });

  tabNav.appendChild(tabList);
  container.appendChild(tabNav);

  // Build panels container
  const panelsContainer = document.createElement('div');
  panelsContainer.className = 'digest-panels';

  // At-a-Glance panel
  const glancePanel = document.createElement('div');
  glancePanel.className = 'digest-panel';
  glancePanel.setAttribute('role', 'tabpanel');
  glancePanel.id = 'panel-glance';

  const glanceContent = document.createElement('div');
  glanceContent.className = 'digest-glance';

  panels.forEach(panel => {
    if (panel.items.length === 0) return;
    const section = document.createElement('div');
    section.className = 'digest-glance-section';

    const catHeader = document.createElement('div');
    catHeader.className = 'digest-glance-category';
    catHeader.textContent = panel.category;
    section.appendChild(catHeader);

    const list = document.createElement('ul');
    list.className = 'digest-glance-list';

    panel.items.forEach(li => {
      const p = li.querySelector('p');
      const strong = p ? p.querySelector('strong') : null;
      const em = p ? p.querySelector('em') : null;
      const a = p ? p.querySelector('a') : null;
      if (!strong || !em || !a) return;

      const title = strong.textContent.trim();
      const source = em.textContent.trim();
      const url = a.getAttribute('href');

      const item = document.createElement('li');
      item.className = 'digest-glance-item';
      item.innerHTML = `<a href="${url}">${title}</a><span class="digest-glance-source">— ${source}</span>`;
      list.appendChild(item);
    });

    section.appendChild(list);
    glanceContent.appendChild(section);
  });

  glancePanel.appendChild(glanceContent);
  panelsContainer.appendChild(glancePanel);

  // Category panels
  panels.forEach((panel, index) => {
    const panelDiv = document.createElement('div');
    panelDiv.className = 'digest-panel';
    panelDiv.setAttribute('role', 'tabpanel');
    panelDiv.id = `panel-${index}`;

    const h2 = document.createElement('h2');
    h2.textContent = panel.category;
    h2.setAttribute('data-category', panel.category);
    panelDiv.appendChild(h2);

    const ul = document.createElement('ul');
    panel.items.forEach(li => {
      const card = document.createElement('li');
      card.className = 'digest-card';

      const p = li.querySelector('p');
      const strong = p ? p.querySelector('strong') : null;
      const em = p ? p.querySelector('em') : null;
      const a = p ? p.querySelector('a') : null;

      const titleEl = document.createElement('div');
      titleEl.className = 'digest-card-title';
      if (strong && a) {
        titleEl.innerHTML = `<a href="${a.getAttribute('href')}">${strong.textContent.trim()}</a>`;
      } else if (strong) {
        titleEl.textContent = strong.textContent.trim();
      }

      const sourceEl = document.createElement('div');
      sourceEl.className = 'digest-card-source';
      if (em) {
        sourceEl.textContent = em.textContent.trim();
      }

      const summaryEl = document.createElement('div');
      summaryEl.className = 'digest-card-summary';
      if (p) {
        const summaryParts = [];
        Array.from(p.childNodes).forEach(node => {
          if (node.nodeType === Node.TEXT_NODE) {
            const text = node.textContent.trim();
            if (text) summaryParts.push(text);
          } else if (node.nodeType === Node.ELEMENT_NODE && 
                     node.tagName !== 'STRONG' && 
                     node.tagName !== 'EM' && 
                     node.tagName !== 'A') {
            summaryParts.push(node.textContent.trim());
          }
        });
        let summary = summaryParts.join(' ').trim();
        summary = summary.replace(/^[—\s]+/, '').trim();
        if (summary) summaryEl.textContent = summary;
      }

      const linkEl = document.createElement('div');
      linkEl.className = 'digest-card-link';
      if (a) {
        linkEl.innerHTML = `<a href="${a.getAttribute('href')}">read ↗</a>`;
      }

      card.appendChild(titleEl);
      card.appendChild(sourceEl);
      if (summaryEl.textContent) card.appendChild(summaryEl);
      if (linkEl.innerHTML) card.appendChild(linkEl);

      ul.appendChild(card);
    });

    panelDiv.appendChild(ul);
    panelsContainer.appendChild(panelDiv);
  });

  container.appendChild(panelsContainer);

  // Tab switching
  function switchTab(tabId) {
    tabs.forEach(t => {
      t.button.setAttribute('aria-selected', t.id === tabId ? 'true' : 'false');
    });

    document.querySelectorAll('.digest-panel').forEach(p => {
      p.classList.toggle('is-active', p.id === `panel-${tabId}`);
    });

    if (tabId === 'glance') {
      window.location.hash = '#glance';
    } else {
      const panel = panels[parseInt(tabId, 10)];
      if (panel) {
        const slug = panel.category.toLowerCase().replace(/[^a-z0-9]+/g, '-');
        window.location.hash = `#${slug}`;
      }
    }
  }

  // Read hash or default to glance
  const hash = window.location.hash.replace('#', '').toLowerCase();
  let initialTab = 'glance';

  if (hash) {
    const matchedTab = tabs.find(t => {
      if (t.id === 'glance') return hash === 'glance';
      const panel = panels[parseInt(t.id, 10)];
      return panel && panel.category.toLowerCase().replace(/[^a-z0-9]+/g, '-') === hash;
    });
    if (matchedTab) initialTab = matchedTab.id;
  }

  switchTab(initialTab);

  tabs.forEach(t => {
    t.button.addEventListener('click', () => switchTab(t.id));
  });

  window.addEventListener('hashchange', () => {
    const newHash = window.location.hash.replace('#', '').toLowerCase();
    const matchedTab = tabs.find(t => {
      if (t.id === 'glance') return newHash === 'glance';
      const panel = panels[parseInt(t.id, 10)];
      return panel && panel.category.toLowerCase().replace(/[^a-z0-9]+/g, '-') === newHash;
    });
    if (matchedTab) switchTab(matchedTab.id);
  });
});
