const Data = {
  cache: null,
  async fetch() {
    if (this.cache) return this.cache;
    try {
      const res = await fetch(window.BASE_URL + '/data/latest.json');
      if (!res.ok) throw new Error('Failed to load data');
      this.cache = await res.json();
      return this.cache;
    } catch (e) {
      console.error(e);
      return null;
    }
  },
  getTop() {
    const data = this.cache;
    if (!data) return [];
    return data.stories.filter(s => s.tier === 'top').sort((a, b) => b.importance - a.importance);
  },
  getMajor() {
    const data = this.cache;
    if (!data) return [];
    return data.stories.filter(s => s.tier === 'major').sort((a, b) => b.importance - a.importance);
  },
  getByCategory(cat) {
    const data = this.cache;
    if (!data) return [];
    return data.stories.filter(s => s.category === cat);
  },
  getByTier(tier) {
    const data = this.cache;
    if (!data) return [];
    return data.stories.filter(s => s.tier === tier);
  },
  getToolOfDay() {
    const data = this.cache;
    if (!data || !data.tool_of_day) return null;
    return data.stories.find(s => s.id === data.tool_of_day) || null;
  },
  getToolsOfDay() {
    const data = this.cache;
    if (!data) return { opensource: null, freemium: null };
    const byId = id => (id ? this.getById(id) : null);
    return {
      opensource: byId(data.tool_of_day_opensource),
      freemium: byId(data.tool_of_day_freemium) || byId(data.tool_of_day)
    };
  },
  getNewAgents() {
    const data = this.cache;
    if (!data) return [];
    return data.stories.filter(s => s.is_new_agent).sort((a, b) => b.importance - a.importance);
  },
  getWhatsNew() {
    const data = this.cache;
    if (!data) return [];
    return data.stories.filter(s => s.is_whats_new)
      .sort((a, b) => new Date(b.published_at) - new Date(a.published_at));
  },
  getEarlySignal() {
    const data = this.cache;
    if (!data || !data.early_signal) return null;
    return data.stories.find(s => s.id === data.early_signal) || null;
  },
  getById(id) {
    const data = this.cache;
    if (!data) return null;
    return data.stories.find(s => s.id === id) || null;
  },
  getRelated(story) {
    const data = this.cache;
    if (!data || !story) return [];
    const tags = new Set(story.tags || []);
    const cat = story.category;
    return data.stories.filter(s => s.id !== story.id && (s.category === cat || s.tags.some(t => tags.has(t)))).slice(0, 4);
  },
  formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  },
  formatTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  }
};
