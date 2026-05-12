import { useCallback, useEffect, useRef } from "react";

/**
 * Grab-to-pan for the gantt-task-react chart.
 *
 * HORIZONTAL PAN
 * --------------
 * gantt-task-react v0.3.9 owns horizontal scroll as internal React state
 * (`scrollX`). It renders a dedicated thin scroll container div (overflow-x:
 * auto with a wide spacer child). When that div's `scrollLeft` changes, the
 * library's own `onScroll` handler fires `setScrollX` — the native path.
 *
 * We locate this div (scrollWidth > clientWidth, height < 20px) and set
 * `scrollLeft` directly. This is synchronous DOM manipulation so it avoids
 * the stale-state problem that synthetic WheelEvents suffer from (multiple
 * events per React render cycle would all read the same `scrollX` closure
 * value, discarding every delta except the last).
 *
 * VERTICAL PAN
 * ------------
 * When ganttHeight is set the library manages vertical scroll via an internal
 * div with overflow-y:auto. We find it (scrollHeight > clientHeight) and
 * adjust its scrollTop directly.
 *
 * DRAG MECHANICS
 * --------------
 * On mousedown we attach document-level mousemove/mouseup listeners so the
 * drag continues even if the cursor leaves the container element. We track the
 * PREVIOUS mouse position (not start) so each mousemove fires an incremental
 * delta rather than a cumulative one.
 */
export function useDragToPan<T extends HTMLElement = HTMLDivElement>() {
  const containerRef = useRef<T>(null);
  const isDragging = useRef(false);
  const lastX = useRef(0);
  const lastY = useRef(0);
  const activeMoveRef = useRef<((e: MouseEvent) => void) | null>(null);
  const activeUpRef = useRef<(() => void) | null>(null);

  const stopDrag = useCallback(() => {
    if (!isDragging.current) return;
    isDragging.current = false;
    if (containerRef.current) {
      containerRef.current.style.cursor = "";
      containerRef.current.style.userSelect = "";
    }
    if (activeMoveRef.current) {
      document.removeEventListener("mousemove", activeMoveRef.current);
      activeMoveRef.current = null;
    }
    if (activeUpRef.current) {
      document.removeEventListener("mouseup", activeUpRef.current);
      activeUpRef.current = null;
    }
  }, []);

  // Clean up if the component unmounts mid-drag.
  useEffect(() => () => stopDrag(), [stopDrag]);

  const onMouseDown = useCallback(
    (e: React.MouseEvent<T>) => {
      if (e.button !== 0) return;
      if (isBarOrHandle(e.target as Element)) return;

      const container = containerRef.current;
      if (!container) return;

      // Prevent browser text-selection drag from competing.
      e.preventDefault();

      isDragging.current = true;
      lastX.current = e.clientX;
      lastY.current = e.clientY;
      container.style.cursor = "grabbing";
      container.style.userSelect = "none";

      const moveHandler = (ev: MouseEvent) => {
        if (!isDragging.current || !containerRef.current) return;

        const dx = ev.clientX - lastX.current;
        const dy = ev.clientY - lastY.current;
        lastX.current = ev.clientX;
        lastY.current = ev.clientY;

        // ── Vertical pan ─────────────────────────────────────────
        // When ganttHeight is set, the library manages vertical scroll via
        // its internal div with overflow-y:auto. Find it by checking which
        // descendant is actually scrollable (scrollHeight > clientHeight).
        if (dy !== 0) {
          let scrollable: HTMLElement = containerRef.current;
          const candidates = containerRef.current.querySelectorAll<HTMLElement>("div");
          for (const el of candidates) {
            if (el.scrollHeight > el.clientHeight + 1 && el.clientHeight > 0) {
              scrollable = el;
              break;
            }
          }
          scrollable.scrollTop -= dy;
        }

        // ── Horizontal pan ───────────────────────────────────────
        // Find the library's horizontal scroll container: a thin div
        // whose scrollWidth > clientWidth (the scrollbar track).
        // Setting scrollLeft directly is synchronous and triggers the
        // library's onScroll → setScrollX, avoiding stale-state issues.
        if (dx !== 0) {
          const divs = containerRef.current.querySelectorAll<HTMLElement>("div");
          for (const el of divs) {
            if (
              el.scrollWidth > el.clientWidth + 1 &&
              el.clientHeight < 20
            ) {
              el.scrollLeft -= dx;
              break;
            }
          }
        }
      };

      const upHandler = () => stopDrag();

      activeMoveRef.current = moveHandler;
      activeUpRef.current = upHandler;

      // Document-level so the drag survives leaving the container.
      document.addEventListener("mousemove", moveHandler);
      document.addEventListener("mouseup", upHandler);
    },
    [stopDrag],
  );

  return { containerRef, onMouseDown };
}

/**
 * Returns true if the pointer-down target is (or is inside) a gantt task bar
 * or its resize handle.
 *
 * WHY rx > 0 (no width/height check)
 * ------------------------------------
 * gantt-task-react renders these SVGRectElements:
 *   • Grid row backgrounds  — rx=0  (full chart width, row height)
 *   • Task bar rects        — rx=barCornerRadius (default 3)
 *   • Bar resize handles    — rx=barCornerRadius, but width=handleWidth (default 8px, << 20px)
 *
 * The previous "w>20 && h>10 && rx>0" check correctly excluded grid rows but
 * also excluded the narrow resize handles, so dragging a handle started our
 * pan at the same time as the library's resize drag.
 *
 * Every SVGRectElement with rx>0 in the gantt DOM is bar-related. All grid /
 * calendar / tick rects are square-cornered (rx=0). Removing the size
 * requirements and keeping only rx>0 is sufficient and correct.
 */
function isBarOrHandle(el: Element | null): boolean {
  let cur = el;
  let depth = 0;
  while (cur && depth < 6) {
    if (cur instanceof SVGRectElement) {
      const rx = cur.rx?.baseVal?.value ?? 0;
      if (rx > 0) return true; // bar rect or resize handle
    }
    if (cur instanceof SVGTextElement) return true; // bar label text
    cur = cur.parentElement;
    depth++;
  }
  return false;
}
