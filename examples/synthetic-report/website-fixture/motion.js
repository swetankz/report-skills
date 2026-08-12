const loader = document.querySelector('.loader');
setTimeout(() => loader.remove(), 50);
setTimeout(() => {
  document.querySelectorAll('section').forEach((section) => {
    section.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 1200 });
  });
}, 600);

