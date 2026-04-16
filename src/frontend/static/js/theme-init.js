(function () {
    var t = localStorage.getItem('fq-theme');
    if (t === 'indigo' || t === 'midnight') {
        document.documentElement.setAttribute('data-theme', t);
    }
})();
