import "@testing-library/jest-dom/vitest";

const elementProto = Element.prototype as Element & {
  scrollIntoView?: (arg?: boolean | ScrollIntoViewOptions) => void;
};
if (!elementProto.scrollIntoView) {
  elementProto.scrollIntoView = () => {};
}
