const LIMIT = 5000;
const clamp = (value) => Math.max(0, Math.min(LIMIT, Math.round(value)));

export function placeNote(note, position) {
  note.style.left = `${position.x}px`;
  note.style.top = `${position.y}px`;
}

export function fitCanvas(canvas) {
  let width = 1200;
  let height = 900;
  for (const note of canvas.children) {
    width = Math.max(width, note.offsetLeft + note.offsetWidth + 40);
    height = Math.max(height, note.offsetTop + note.offsetHeight + 80);
  }
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
}

// A dedicated handle keeps inputs, task checkboxes and text selection usable.
// Pointer events support mouse, pen and touch; arrow keys provide an alternative.
export function enableNoteMovement(note, handle, initial, { save, onError, onStatus }) {
  let saved = { ...initial };
  let position = { ...initial };
  let drag = null;
  let saving = false;
  const canvas = note.parentElement;
  const viewport = canvas.parentElement;

  function paint(next) {
    position = { x: clamp(next.x), y: clamp(next.y) };
    placeNote(note, position);
    fitCanvas(canvas);
  }

  function raise() {
    for (const sibling of canvas.children) sibling.style.zIndex = '';
    note.style.zIndex = '1';
  }

  async function commit() {
    if (saving || (position.x === saved.x && position.y === saved.y)) return;
    saving = true;
    // Keep keyboard focus while saving; the guards below block further moves.
    handle.setAttribute('aria-disabled', 'true');
    note.setAttribute('aria-busy', 'true');
    onStatus('Saving note position…');
    try {
      const result = await save({ ...position });
      saved = { ...result.position };
      paint(saved);
      onStatus('Note position saved.');
    } catch (error) {
      paint(saved);
      onStatus('Note returned to its last saved position.');
      onError(error);
    } finally {
      saving = false;
      handle.removeAttribute('aria-disabled');
      note.removeAttribute('aria-busy');
    }
  }

  handle.addEventListener('pointerdown', (event) => {
    if (saving || event.button !== 0) return;
    event.preventDefault();
    handle.focus();
    raise();
    drag = {
      id: event.pointerId, x: event.clientX, y: event.clientY,
      start: { ...position }, scrollX: viewport.scrollLeft, scrollY: viewport.scrollTop,
    };
    handle.setPointerCapture(event.pointerId);
    note.classList.add('dragging');
  });
  handle.addEventListener('pointermove', (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    paint({
      x: drag.start.x + event.clientX - drag.x + viewport.scrollLeft - drag.scrollX,
      y: drag.start.y + event.clientY - drag.y + viewport.scrollTop - drag.scrollY,
    });
  });
  handle.addEventListener('pointerup', (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    drag = null;
    note.classList.remove('dragging');
    handle.releasePointerCapture(event.pointerId);
    commit();
  });
  function cancelDrag() {
    if (!drag) return;
    paint(drag.start);
    drag = null;
    note.classList.remove('dragging');
  }
  handle.addEventListener('pointercancel', cancelDrag);
  handle.addEventListener('lostpointercapture', cancelDrag);
  handle.addEventListener('keydown', (event) => {
    if (saving) {
      if (event.key.startsWith('Arrow')) event.preventDefault();
      return;
    }
    if (event.key === 'Escape') {
      cancelDrag();
      paint(saved);
      return;
    }
    const directions = {
      ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
    };
    const direction = directions[event.key];
    if (!direction || drag) return;
    event.preventDefault();
    raise();
    const step = event.shiftKey ? 50 : 10;
    paint({ x: position.x + direction[0] * step, y: position.y + direction[1] * step });
  });
  handle.addEventListener('keyup', (event) => {
    if (event.key.startsWith('Arrow') && !drag) commit();
  });
  handle.addEventListener('blur', () => { if (!drag) commit(); });
}
