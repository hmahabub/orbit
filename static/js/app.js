// Orbit ERP — small progressive enhancements. Every total shown live here is
// recomputed on the server when the form is saved.
(function () {
  'use strict';

  var fmt = function (n, places) {
    return Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: places, maximumFractionDigits: places });
  };
  var val = function (el) { var v = parseFloat(el && el.value); return isNaN(v) ? 0 : v; };

  document.addEventListener('DOMContentLoaded', function () {
    // Auto-dismiss success/info alerts.
    document.querySelectorAll('.alert-success, .alert-info').forEach(function (el) {
      if (!el.classList.contains('alert-dismissible')) return;
      setTimeout(function () { bootstrap.Alert.getOrCreateInstance(el).close(); }, 5000);
    });

    // Confirm before destructive buttons.
    document.addEventListener('click', function (e) {
      var el = e.target.closest('[data-confirm]');
      if (el && !confirm(el.getAttribute('data-confirm'))) e.preventDefault();
    });

    // Whole-row links on the orders list.
    document.querySelectorAll('tr.clickable').forEach(function (tr) {
      tr.addEventListener('click', function (e) {
        if (!e.target.closest('a, button, input')) window.location = tr.dataset.href;
      });
    });

    // "Tick all lines" in a supplier PO's header.
    document.querySelectorAll('.check-all').forEach(function (box) {
      box.addEventListener('change', function () {
        box.closest('table').querySelectorAll('tbody input[name="line"]').forEach(function (c) { c.checked = box.checked; });
      });
    });

    initAssortment();
    initBom();
    initCosting();
  });

  // ---- Assortment grid ---------------------------------------------------
  function initAssortment() {
    var table = document.getElementById('assortTable');
    if (!table) return;
    var tbody = table.tBodies[0];
    var tpl = document.getElementById('assortRowTpl');
    var next = tbody.rows.length;

    function addRow() {
      var html = tpl.innerHTML.replace(/__N__/g, String(next++));
      tbody.insertAdjacentHTML('beforeend', html);
      return tbody.rows[tbody.rows.length - 1];
    }

    function recalc() {
      var cols = table.querySelectorAll('tfoot .col-total');
      var colSums = Array(cols.length).fill(0), grand = 0;
      Array.prototype.forEach.call(tbody.rows, function (tr) {
        var sum = 0;
        tr.querySelectorAll('.size-grid-input').forEach(function (inp, j) { var v = val(inp); sum += v; colSums[j] += v; });
        tr.querySelector('.row-total').textContent = fmt(sum, 0);
        grand += sum;
      });
      cols.forEach(function (th, j) { th.textContent = fmt(colSums[j], 0); });
      table.querySelector('.grand-total').textContent = fmt(grand, 0);
      var lineQty = parseInt(table.dataset.lineQty, 10), diff = grand - lineQty;
      var check = document.getElementById('assortCheck');
      check.className = 'small fw-semibold ' + (diff === 0 ? 'text-success' : 'text-danger');
      check.innerHTML = diff === 0
        ? '<i class="bi bi-check-circle-fill"></i> Matches line qty ' + fmt(lineQty, 0)
        : '<i class="bi bi-exclamation-triangle-fill"></i> ' + fmt(grand, 0) + ' of ' + fmt(lineQty, 0) + ' pcs (' + (diff > 0 ? '+' : '') + fmt(diff, 0) + ')';
    }

    function relabel() {
      var checked = document.querySelector('input[name="size_type"]:checked');
      if (!checked) return;
      var labels = table.dataset[checked.value].split(',');
      table.querySelectorAll('.size-head').forEach(function (th, j) { th.textContent = labels[j]; });
    }

    if (!tbody.rows.length) { addRow(); addRow(); addRow(); }
    document.getElementById('addColor').addEventListener('click', function () { addRow().querySelector('input').focus(); });
    tbody.addEventListener('click', function (e) {
      if (e.target.closest('.remove-row')) { e.target.closest('tr').remove(); recalc(); }
    });
    table.addEventListener('input', recalc);
    document.querySelectorAll('input[name="size_type"]').forEach(function (r) { r.addEventListener('change', relabel); });
    relabel();
    recalc();
  }

  // ---- BOM: consumption <-> total requirement ----------------------------
  // Like Excel: type either one and the other follows. The hidden `src` field
  // tells the server which one the user typed last.
  function initBom() {
    document.querySelectorAll('tr.calc-row').forEach(function (tr) {
      var cons = tr.querySelector('.js-cons'), qty = tr.querySelector('.js-qty'),
          req = tr.querySelector('.js-req'), src = tr.querySelector('.js-src');
      var round = function (n, p) { return String(Math.round(n * Math.pow(10, p)) / Math.pow(10, p)); };
      var orderQty = function () { return qty.value === '' ? parseFloat(tr.dataset.auto) || 0 : val(qty); };
      cons.addEventListener('input', function () {
        src.value = 'cons';
        req.value = round(orderQty() * val(cons), 2);
      });
      req.addEventListener('input', function () {
        src.value = 'req';
        var q = orderQty();
        cons.value = q ? round(val(req) / q, 6) : '0';
      });
      qty.addEventListener('input', function () {
        qty.classList.toggle('overridden', qty.value !== '');
        var q = orderQty();
        if (src.value === 'req') cons.value = q ? round(val(req) / q, 6) : '0';
        else req.value = round(q * val(cons), 2);
      });
    });
    // Item-name cells grow with their text, like a wrapped Excel cell.
    document.querySelectorAll('.sheet textarea').forEach(function (ta) {
      var fit = function () { ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; };
      ta.addEventListener('input', fit);
      fit();
    });
  }

  // ---- Costing -----------------------------------------------------------
  function initCosting() {
    var table = document.getElementById('costTable');
    if (!table) return;
    var summary = document.querySelector('.cost-summary');

    function recalc() {
      var total = 0;
      table.querySelectorAll('tr.price-row').forEach(function (tr) {
        var price = tr.querySelector('.js-price');
        var amount = parseFloat(tr.dataset.req) * val(price);
        tr.querySelector('.js-amount').textContent = fmt(amount, 2);
        price.classList.toggle('is-missing', price.value === '');
        total += amount;
      });
      document.getElementById('materialTotal').textContent = fmt(total, 2);
      var qty = parseFloat(summary.dataset.qty) || 1, fob = parseFloat(summary.dataset.fob) || 0;
      var pc = total / qty, totalPc = pc + (parseFloat(summary.dataset.extras) || 0), margin = fob - totalPc;
      document.getElementById('sumDz').textContent = fmt(pc * 12, 4);
      document.getElementById('sumPc').textContent = fmt(pc, 4);
      document.getElementById('sumTotal').textContent = fmt(totalPc, 4);
      var m = document.getElementById('sumMargin');
      m.textContent = fmt(margin, 4);
      m.className = 'col-5 text-end fw-bold ' + (margin < 0 ? 'text-danger' : 'text-success');
      document.getElementById('sumMarginPct').textContent = fmt(fob ? margin / fob * 100 : 0, 1) + '%';
      document.getElementById('sumMarginTotal').textContent = fmt(margin * qty, 2);
    }

    table.addEventListener('input', function (e) { if (e.target.classList.contains('js-price')) recalc(); });
    table.addEventListener('click', function (e) {
      var btn = e.target.closest('.apply-all-price');
      if (!btn) return;
      var tr = btn.closest('tr'), value = btn.closest('.set-all').querySelector('.set-all-price').value;
      var itemId = tr.querySelector('.js-price').dataset.item;
      table.querySelectorAll('.js-price[data-item="' + itemId + '"]').forEach(function (inp) { inp.value = value; });
      recalc();
    });
  }
})();
