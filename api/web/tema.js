/* Tema claro/escuro das duas páginas.

   Carregado de forma síncrona no <head>, antes das folhas de estilo: o `data-tema` já está na
   raiz quando a página pinta pela primeira vez, então ela não pisca no tema errado. A escolha
   fica no localStorage; sem escolha, segue o tema do sistema.

   Os gráficos guardam as cores do momento em que foram criados. Por isso a troca dispara o
   evento `tema` no document, e cada página redesenha os seus. */
(function () {
  const raiz = document.documentElement;
  let salvo = null;
  try {
    salvo = localStorage.getItem('tema');
  } catch (e) {
    // armazenamento bloqueado pelo navegador: segue o sistema
  }
  const sistema = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'escuro' : 'claro';
  raiz.dataset.tema = salvo === 'claro' || salvo === 'escuro' ? salvo : sistema;

  document.addEventListener('DOMContentLoaded', () => {
    const botao = document.getElementById('alternar-tema');
    if (!botao) return;

    const rotular = () => {
      const escuro = raiz.dataset.tema === 'escuro';
      botao.textContent = escuro ? '☀ Modo claro' : '☾ Modo escuro';
      botao.setAttribute('aria-label', escuro ? 'Mudar para o modo claro' : 'Mudar para o modo escuro');
    };
    rotular();

    botao.addEventListener('click', () => {
      raiz.dataset.tema = raiz.dataset.tema === 'escuro' ? 'claro' : 'escuro';
      try {
        localStorage.setItem('tema', raiz.dataset.tema);
      } catch (e) {
        // sem armazenamento: vale só para esta visita
      }
      rotular();
      document.dispatchEvent(new CustomEvent('tema'));
    });
  });
})();
