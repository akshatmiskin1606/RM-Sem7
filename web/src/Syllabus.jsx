import React, { useState } from 'react';

const levels = { document: 'Document', chapter: 'Chapter', subtopic: 'Subtopic', keyword: 'Keyword', page: 'Page' };

export function indexTopics(root, topics = new Map()) {
  if (root) {
    topics.set(root.id, root);
    for (const child of root.children) indexTopics(child, topics);
  }
  return topics;
}

function Branch({ topic, selected, inherited, disabled, onToggle }) {
  const [open, setOpen] = useState(topic.kind === 'document');
  const hasChildren = topic.children.length > 0;
  const included = inherited || selected.has(topic.id);
  const childrenId = `syllabus-${topic.id}`;
  const branchLabel = <><span className="outline-title">{topic.title}</span><small>{levels[topic.kind]}</small></>;
  return <li className={`outline-branch ${topic.kind}`}>
    <div className={`outline-row${included ? ' included' : ''}`}>
      {hasChildren
        ? <button type="button" className="outline-title-button" aria-expanded={open} aria-controls={childrenId} onClick={() => setOpen(!open)}>
          <span className="outline-chevron" aria-hidden="true">›</span>{branchLabel}
        </button>
        : <span className="outline-leaf"><span className="outline-dot" aria-hidden="true" />{branchLabel}</span>}
      {topic.selectable && <input type="checkbox" checked={included} disabled={disabled || inherited}
        aria-label={`Include ${topic.title}`} onChange={() => onToggle(topic)} />}
    </div>
    {hasChildren && <ul className="outline-children" id={childrenId} hidden={!open}>
      {open && topic.children.map(child => <Branch key={child.id} topic={child} selected={selected} inherited={included}
        disabled={disabled} onToggle={onToggle} />)}
    </ul>}
  </li>;
}

export function SyllabusOutline({ root, selected, disabled, onToggle }) {
  return <div className="syllabus-outline" aria-label="Knowledge graph by chapter">
    <ul className="outline-root"><Branch topic={root} selected={selected} inherited={false} disabled={disabled} onToggle={onToggle} /></ul>
  </div>;
}

export function SyllabusControl({ selected, topics, disabled, onClear }) {
  return <div className="syllabus-control">
    <div className="syllabus-control-heading"><h3>Syllabus Control</h3>
      {selected.length > 0 && <button type="button" className="text-button" disabled={disabled} onClick={onClear}>Clear</button>}
    </div>
    <p>{selected.length ? `${selected.length} ${selected.length === 1 ? 'topic' : 'topics'} selected` : 'Whole document selected'}</p>
    {selected.length ? <ul className="selected-topics">
      {selected.map(id => <li key={id}>{topics.get(id)?.title || id}</li>)}
    </ul> : <p className="control-note">Check topics in the chapter view to narrow the question batch.</p>}
  </div>;
}
