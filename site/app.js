// 価格帯・送料無料での絞り込み (ジャンル別ページのみ)
(function () {
  var box = document.querySelector(".filters");
  if (!box) return;
  var cards = Array.prototype.slice.call(document.querySelectorAll(".ranking .card"));
  var buttons = Array.prototype.slice.call(box.querySelectorAll("button"));
  var freeOnly = box.querySelector(".free-only");
  var count = box.querySelector(".count");
  var empty = document.querySelector(".ranking .empty");
  var min = 0;
  var max = 0;

  function apply() {
    var shown = 0;
    cards.forEach(function (card) {
      var price = Number(card.getAttribute("data-price")) || 0;
      var ok = price >= min && (max === 0 || price < max);
      if (freeOnly.checked && card.getAttribute("data-free") !== "1") ok = false;
      card.hidden = !ok;
      if (ok) shown++;
    });
    count.textContent = shown + "件 / " + cards.length + "件を表示中";
    empty.hidden = shown !== 0;
  }

  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      buttons.forEach(function (b) { b.setAttribute("aria-pressed", String(b === btn)); });
      min = Number(btn.getAttribute("data-min"));
      max = Number(btn.getAttribute("data-max"));
      apply();
    });
  });
  freeOnly.addEventListener("change", apply);

  // 選択中のタブが見える位置までタブ列をスクロール
  var current = document.querySelector('.tabs [aria-current="page"]');
  if (current && current.scrollIntoView) current.scrollIntoView({ block: "nearest", inline: "center" });

  box.hidden = false;
  apply();
})();
