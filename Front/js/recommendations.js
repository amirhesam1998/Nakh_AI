/**
 * Recommendations page logic.
 *
 * On load: reads upload_id from URL, POSTs to /api/v1/recommendations,
 * displays the LLM text and product cards.
 */
(function ($) {
  $(function () {
    var apiUrl = window.apiUrl || function (path) { return path; };

    var urlParams = new URLSearchParams(window.location.search);
    var uploadId = urlParams.get("upload_id") || "";

    var $loading  = $("#recLoading");
    var $results  = $("#recResults");
    var $error    = $("#recError");
    var $errorMsg = $("#recErrorMsg");
    var $recText  = $("#recText");
    var $recProducts = $("#recProducts");

    function showError(msg) {
      $loading.hide();
      $results.hide();
      $errorMsg.text(msg || "خطا در دریافت پیشنهادات");
      $error.show();
    }

    function renderProducts(products) {
      if (!products || !products.length) return;

      var html = "";
      products.forEach(function (p) {
        var name  = p.name_fa || p.name || "محصول";
        var price = p.price ? Number(p.price).toLocaleString("fa-IR") + " تومان" : "";
        var cat   = p.category || "";
        html += '<div class="product-card">';
        html += '  <h4>' + name + '</h4>';
        if (price) html += '  <div class="price">' + price + '</div>';
        if (cat)   html += '  <div class="category">' + cat + '</div>';
        html += '</div>';
      });
      $recProducts.html(html);
    }

    // Auth header
    var authHeaders = {};
    var savedToken = localStorage.getItem("auth_token");
    if (savedToken) {
      authHeaders["Authorization"] = "Bearer " + savedToken;
    }

    var payload = {};
    if (uploadId) payload.upload_id = uploadId;

    $.ajax({
      url: apiUrl("/recommendations", "secondary"),
      method: "POST",
      headers: authHeaders,
      contentType: "application/json",
      data: JSON.stringify(payload),
      dataType: "json",
      timeout: 180000, // 3 minutes for CPU inference
    })
      .done(function (data) {
        $loading.hide();
        $recText.text(data.recommendations_text || "");
        renderProducts(data.products || []);
        $results.show();
      })
      .fail(function (xhr, statusText, err) {
        console.error("Recommendations error:", statusText, err);
        var msg = "خطا در دریافت پیشنهادات.";
        if (xhr.status === 404) msg = "آپلودی یافت نشد.";
        if (xhr.status === 401) msg = "لطفاً ابتدا وارد شوید.";
        showError(msg);
      });
  });
})(window.jQuery);
