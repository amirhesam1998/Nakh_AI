/**
 * Recommendations page logic.
 *
 * On load: reads upload_id from URL, POSTs to /api/v1/recommendations,
 * displays the LLM text, calculated size, and product cards filtered
 * to the user's body measurements.
 */
(function ($) {
  $(function () {
    var apiUrl = window.apiUrl || function (path) { return path; };

    var urlParams = new URLSearchParams(window.location.search);
    var uploadId = urlParams.get("upload_id") || "";

    var $loading     = $("#recLoading");
    var $results     = $("#recResults");
    var $error       = $("#recError");
    var $errorMsg    = $("#recErrorMsg");
    var $recText     = $("#recText");
    var $recProducts = $("#recProducts");
    var $sizeInfo    = $("#sizeInfo");
    var $sizeLabel   = $("#sizeLabel");
    var $sizeDetails = $("#sizeDetails");

    function showError(msg) {
      $loading.hide();
      $results.hide();
      $errorMsg.text(msg || "خطا در دریافت پیشنهادات");
      $error.show();
    }

    /** Render the calculated size badge and details */
    function renderSizeInfo(data) {
      var sizeInfo = data.calculated_size;
      if (!sizeInfo || !sizeInfo.size) {
        $sizeInfo.hide();
        return;
      }

      var label = sizeInfo.size;
      if (sizeInfo.size_numeric) {
        label += " (EU " + sizeInfo.size_numeric + ")";
      }
      $sizeLabel.text(label);

      // Details breakdown
      var details = sizeInfo.details || {};
      var parts = [];
      if (details.chest) parts.push("سینه: " + details.chest);
      if (details.waist) parts.push("کمر: " + details.waist);
      if (details.hip)   parts.push("باسن: " + details.hip);
      $sizeDetails.text(parts.length ? parts.join(" | ") : "");

      $sizeInfo.show();
    }

    /** Resolve the product page URL from API data or construct a fallback. */
    function getProductUrl(p) {
      // Prefer the direct URL from the CMS
      if (p.product_url && p.product_url !== "#") return p.product_url;
      // Fallback: build from CMS base + slug
      if (p.slug) {
        var shopBase = (window.API_CONFIG.BASE_URL || "").replace(/\/api\/v1\/?$/, "");
        return shopBase + "/products/" + p.slug;
      }
      return "";
    }

    /** Format a number as Persian-locale price string. */
    function formatPrice(val) {
      if (!val) return "";
      return Number(val).toLocaleString("fa-IR") + " تومان";
    }

    /** Build a product card HTML */
    function buildProductCard(p) {
      var name  = p.title || p.name_fa || p.name || "محصول";
      var brand = p.brand || "";
      var img   = p.image || "";
      var cat   = p.category || "";
      var matchedSize = p.matched_size || "";
      var matchedVariant = p.matched_variant || null;
      var productUrl = getProductUrl(p);
      var isAvailable = p.is_available !== false;

      // Determine display price (from matched variant or base product)
      var displayPrice = "";
      var regularPrice = "";
      var discountPct  = 0;
      if (matchedVariant && matchedVariant.price) {
        displayPrice = formatPrice(matchedVariant.price);
        discountPct  = matchedVariant.discount || 0;
        // Show regular price only if there's a discount
        if (discountPct > 0 && p.regular_price && Number(p.regular_price) > Number(matchedVariant.price)) {
          regularPrice = formatPrice(p.regular_price);
        }
      } else {
        displayPrice = formatPrice(p.price);
        if (p.regular_price && p.price && Number(p.regular_price) > Number(p.price)) {
          regularPrice = formatPrice(p.regular_price);
          // Compute discount percentage
          discountPct = Math.round((1 - Number(p.price) / Number(p.regular_price)) * 100);
        }
      }

      // Wrap entire card in an anchor if URL exists
      var html = "";
      if (productUrl) {
        html += '<a href="' + productUrl + '" target="_blank" class="product-card-link">';
      }
      html += '<div class="product-card' + (isAvailable ? '' : ' out-of-stock') + '">';

      // Image
      if (img) {
        html += '<div class="product-img-wrap">';
        html += '<img src="' + img + '" alt="' + name + '" class="product-img" />';
        // Availability overlay
        if (!isAvailable) {
          html += '<span class="stock-overlay">ناموجود</span>';
        }
        html += '</div>';
      }

      // Name
      html += '<h4 class="product-name">' + name + '</h4>';

      // Brand
      if (brand) html += '<div class="brand">' + brand + '</div>';

      // Matched size badge
      if (matchedSize) {
        html += '<div class="size-badge">سایز شما: <strong>' + matchedSize + '</strong></div>';
      }

      // Price block
      if (displayPrice) {
        html += '<div class="price-block">';
        if (regularPrice) {
          html += '<span class="regular-price">' + regularPrice + '</span>';
        }
        html += '<span class="price">' + displayPrice + '</span>';
        if (discountPct > 0) {
          html += '<span class="discount-badge">' + discountPct + '%</span>';
        }
        html += '</div>';
      }

      // Availability text (when no image to show overlay on)
      if (!img) {
        html += '<div class="availability ' + (isAvailable ? 'in-stock' : 'no-stock') + '">';
        html += isAvailable ? 'موجود' : 'ناموجود';
        html += '</div>';
      }

      // Category
      if (cat) html += '<div class="category">' + cat + '</div>';

      // Available sizes chips
      var variants = p.variants || [];
      if (variants.length > 0) {
        var sizes = [];
        variants.forEach(function (v) {
          var attrs = v.attributes || {};
          Object.keys(attrs).forEach(function (gn) {
            if (gn.indexOf("اندازه") !== -1 || gn.toLowerCase().indexOf("size") !== -1) {
              var s = attrs[gn];
              if (sizes.indexOf(s) === -1) sizes.push(s);
            }
          });
        });
        if (sizes.length > 0) {
          html += '<div class="available-sizes">';
          sizes.forEach(function (s) {
            var cls = (matchedSize && s.toUpperCase() === matchedSize.toUpperCase())
              ? "size-chip active" : "size-chip";
            html += '<span class="' + cls + '">' + s + '</span>';
          });
          html += '</div>';
        }
      }

      // CTA button
      if (productUrl) {
        html += '<span class="view-btn">' + (isAvailable ? 'مشاهده و خرید' : 'مشاهده محصول') + '</span>';
      }

      html += '</div>';
      if (productUrl) html += '</a>';
      return html;
    }

    function renderProducts(products) {
      if (!products || !products.length) {
        $recProducts.html('<p style="text-align:center;color:#888;">محصولی یافت نشد.</p>');
        return;
      }

      var html = "";
      products.forEach(function (p) {
        html += buildProductCard(p);
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
      timeout: 180000,
    })
      .done(function (data) {
        $loading.hide();
        renderSizeInfo(data);
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
