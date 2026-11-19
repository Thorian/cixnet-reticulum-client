/** Local credits stay in the client, preserving conversations and page state. */
import { $, showDialog } from "./core.js";

/** Wire the About dialog and load bundled credits only when requested. */
export function initAbout() {
  const content = $("about-content");
  let page = null;
  const back = $("about-back");

  /** Restore the credits view after reading a bundled license. */
  function showCredits() {
    content.replaceChildren(page);
    back.hidden = true;
  }

  for (const link of document.querySelectorAll('a[href="about.html"]')) {
    /** Open the About dialog and load its local page on first use. */
    link.onclick = async (event) => {
      event.preventDefault();
      showDialog("about-dialog");
      try {
        if (!page) {
          const response = await fetch("about.html");
          if (!response.ok)
            throw new Error("Could not load local project information");
          // This is our bundled, trusted document, never a Reticulum page.
          const document = new DOMParser().parseFromString(
            await response.text(),
            "text/html",
          );
          page = document.querySelector("main");
          if (!page) throw new Error("Project information is unavailable");
          page.querySelector(".about-header")?.remove();
        }
        showCredits();
      } catch (error) {
        content.textContent = error.message;
      }
    };
  }
  back.onclick = showCredits;
  /** Open the selected bundled license inside the existing dialog. */
  content.onclick = async (event) => {
    const link = event.target.closest('a[href^="licenses/"]');
    if (!link) return;
    event.preventDefault();
    try {
      const response = await fetch(link.getAttribute("href"));
      if (!response.ok) throw new Error("Could not load the local license");
      const text = document.createElement("pre");
      text.className = "license-text";
      text.textContent = await response.text();
      content.replaceChildren(text);
      back.hidden = false;
    } catch (error) {
      content.textContent = error.message;
      back.hidden = false;
    }
  };
}
