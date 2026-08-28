/** Reusable feedback views, isolated from dashboard state and business actions. */
(function (global) {
  function create({query, openModal, closeModal}) {
    function showModal(title, message, kind = 'error') {
      let modal = query('#modal');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'modal'; modal.className = 'modal-overlay';
        modal.innerHTML = '<div class="modal-box"><h3 class="modal-title"></h3><p class="modal-msg"></p><div class="modal-actions"><button class="primary modal-ok">知道了</button></div></div>';
        document.body.appendChild(modal);
        modal.addEventListener('click', event => { if (event.target === modal || event.target.classList.contains('modal-ok')) closeModal(modal); });
      }
      query('.modal-title', modal).textContent = title;
      query('.modal-title', modal).className = 'modal-title ' + kind;
      query('.modal-msg', modal).textContent = message;
      openModal(modal);
    }
    function toast(message, good = true) {
      let host = query('#toastHost');
      if (!host) {
        host = document.createElement('div'); host.id = 'toastHost'; host.className = 'toast-host';
        host.setAttribute('aria-live', 'polite'); host.setAttribute('role', 'status');
        document.body.appendChild(host);
      }
      const element = document.createElement('div');
      element.className = 'toast ' + (good ? 'toast-ok' : 'toast-err'); element.textContent = message;
      host.appendChild(element);
      setTimeout(() => { element.style.opacity = '0'; element.style.transform = 'translateY(6px)'; setTimeout(() => element.remove(), 320); }, 3500);
    }
    return {showModal, toast};
  }
  global.TaskVergeViews = {create};
})(window);
