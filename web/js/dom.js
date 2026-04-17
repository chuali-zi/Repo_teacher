// Tiny DOM helpers. No framework. Strings only — never inject untrusted HTML.

export function el(tag, attrs = null, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
      else if (k === "dataset" && typeof v === "object") Object.assign(node.dataset, v);
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "html") node.innerHTML = v; // explicit opt-in
      else if (v === true) node.setAttribute(k, "");
      else node.setAttribute(k, String(v));
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    if (child instanceof Node) node.appendChild(child);
    else node.appendChild(document.createTextNode(String(child)));
  }
  return node;
}

export function frag(...children) {
  const f = document.createDocumentFragment();
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    if (child instanceof Node) f.appendChild(child);
    else f.appendChild(document.createTextNode(String(child)));
  }
  return f;
}

export function clone(templateId) {
  const tmpl = document.getElementById(templateId);
  if (!(tmpl instanceof HTMLTemplateElement)) {
    throw new Error(`template missing: ${templateId}`);
  }
  return tmpl.content.firstElementChild.cloneNode(true);
}

export function clear(node) {
  while (node && node.firstChild) node.removeChild(node.firstChild);
}

export function $(sel, root = document) {
  return root.querySelector(sel);
}
