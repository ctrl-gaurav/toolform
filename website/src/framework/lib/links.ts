/* Outside links: the documentation (a separate VitePress site under /docs/), the paper page (a static
   page under /paper/), GitHub and PyPI. */
export const DOCS = `${import.meta.env.BASE_URL}docs/`;
export const docs = (page = "") => `${DOCS}${page}`;
export const PAPER = `${import.meta.env.BASE_URL}paper/`;
export const GITHUB = "https://github.com/ctrl-gaurav/toolform";
export const PYPI = "https://pypi.org/project/toolform/";
