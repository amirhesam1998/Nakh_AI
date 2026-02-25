/* Auto-generated bundle: measure.js + check.js */

/* ===== BEGIN measure.js (original content below; unmodified) ===== */
;(function() {
  try {
    if (typeof document !== 'undefined' && document.querySelector('.upload-form')) {
      // --- BEGIN original file (measure.js) ---
;(($) => {
  $(() => {
    const apiUrl = window.apiUrl || ((path) => path)
    const API_UPLOAD_URL = apiUrl("/uploads", "secondary")

    // Initialize upload areas (adjust selectors to match your HTML)
    setupUploadArea("#uploadArea1", "#photo1", "#previewArea1")
    setupUploadArea("#uploadArea2", "#photo2", "#previewArea2")
    setupUploadArea("#uploadArea3", "#photo3", "#previewArea3")

    showGuidanceModal()

    // Hook form submit validation
    const $form = $("form") // or $("#yourFormId") if you have a specific form id
    // جایگزین کنید: $form.on("submit", (e) => { ... })
$form.on("submit", (e) => {
  e.preventDefault();

  // Prevent double submissions
  if ($form.data("submitting")) return;
  
  const $photo1 = $("#photo1")
  const $photo2 = $("#photo2")
  const $photo3 = $("#photo3")
  const $height = $("#height_cm")
  const $weight = $("#weight_kg")
  const $gender = $("#gender")

  const missing = []

  if (!$photo1[0] || !$photo1[0].files || !$photo1[0].files.length) missing.push("عکس جلو")
  if (!$photo2[0] || !$photo2[0].files || !$photo2[0].files.length) missing.push("عکس پشت")
  if (!$photo3[0] || !$photo3[0].files || !$photo3[0].files.length) missing.push("عکس کناری")
  if (!$height.val()) missing.push("قد")
  if (!$weight.val()) missing.push("وزن")
  if (!$gender.val()) missing.push("جنسیت")

  if (missing.length > 0) {
    showWarning(missing)
    return false
  }

  // Ensure loading modal exists (create if missing)
  if (!$("#loadingModal").length) {
    const modalHtml = '\
      <div class="loading-modal" id="loadingModal" style="display:none">\
      <div class="loading-content">\
        <span class="loader"></span>\
        <h3 class="loading-text">در حال پردازش تصویر...</h3>\
        </div>\
      </div>'
    $("body").append(modalHtml)
  }

  // Show modal (use CSS class 'show' if you have it, otherwise use display)
  const $loading = $("#loadingModal")
  $loading.addClass("show").css("display", "flex") // adjust display type if your CSS expects block/flex

  // Mark submitting to prevent duplicates
  $form.data("submitting", true)

  const formEl = $form[0]
  const formData = formEl ? new FormData(formEl) : new FormData()

  var authHeaders = {};
  var savedToken = localStorage.getItem("auth_token");
  if (savedToken) {
    authHeaders["Authorization"] = "Bearer " + savedToken;
  }

  $.ajax({
    url: API_UPLOAD_URL,
    method: "POST",
    headers: authHeaders,
    data: formData,
    processData: false,
    contentType: false,
    timeout: 60000,
    success: function (response) {
      var uploadId = response && response.id;
      if (!uploadId) {
        window.location.href = "check.html";
        return;
      }

      // Update loading text
      $loading.find(".loading-text").text("در حال پردازش هوش مصنوعی...");

      // Poll until processing completes, then redirect
      var resultsUrl = apiUrl("/uploads/" + uploadId + "/results", "secondary");
      function waitForProcessing() {
        $.ajax({
          url: resultsUrl,
          method: "GET",
          headers: authHeaders,
          success: function(data) {
            if (data.status === "processing" || data.status === "pending") {
              setTimeout(waitForProcessing, 3000);
            } else {
              // Processing done — redirect to check page
              window.location.href = "check.html?upload_id=" + encodeURIComponent(uploadId);
            }
          },
          error: function() {
            // Retry on network errors
            setTimeout(waitForProcessing, 3000);
          }
        });
      }
      waitForProcessing();
    },
    error: function (jqXHR, textStatus) {
      console.error("Upload error:", textStatus, jqXHR)
      alert("ارور در ارسال داده‌ها رخ داد. لطفاً دوباره تلاش کنید.")
      $form.data("submitting", false)
      $loading.removeClass("show").css("display", "none")
    },
    complete: function () {
      // Don't hide loading here — waitForProcessing handles the redirect
    },
  })

  return false
})


    // Close warning (delegated, in case modal inserted later)
    $(document)
      .off("click", ".warning-close-btn")
      .on("click", ".warning-close-btn", function () {
        const $overlay = $(this).closest(".validation-warning")
        $overlay.removeClass("show")
        setTimeout(() => $overlay.remove(), 200)
      })

    $("#upload-form-help").on("click", () => {
      showGuidanceModal()
    })

    $(document).on("click", ".guidance-close-btn", () => {
      const $modal = $("#guidanceModal")
      $modal.removeClass("show")
    })

    $(document).on("click", ".viewer-close-btn", () => {
      const $modal = $("#imageViewerModal")
      $modal.removeClass("show")
    })

    $(document).on("click", ".guidance-modal.show, .image-viewer-modal.show", function (e) {
      if ($(e.target).hasClass("guidance-modal") || $(e.target).hasClass("image-viewer-modal")) {
        $(this).removeClass("show")
      }
    })

    // Remove uploaded image (delegated)
    $(document)
      .off("click", ".remove-image")
      .on("click", ".remove-image", function () {
        const $btn = $(this)
        const areaSel = $btn.data("area")
        const inputSel = $btn.data("input")
        const previewSel = $btn.data("preview")

        const $area = $(areaSel)
        const $input = $(inputSel)
        const $preview = $(previewSel)
        const $content = $area.find(".upload-content")

        // Reset
        $input.val("")
        $preview.empty().hide()
        $content.css("display", "flex")
      })

    /**
     * Setup one upload area
     * @param {string} areaSel - container selector (click/drag target)
     * @param {string} inputSel - file input selector
     * @param {string} previewSel - preview container selector
     */
    function setupUploadArea(areaSel, inputSel, previewSel) {
      const $area = $(areaSel)
      const $input = $(inputSel)
      const $preview = $(previewSel)
      const $content = $area.find(".upload-content")

      if (!$area.length || !$input.length || !$preview.length) {
        // Silently ignore if one of the selectors doesn't exist
        return
      }

      // Click to open file picker
      $area.on("click", (e) => {
        // Avoid triggering if click is on the remove button inside preview
        if ($(e.target).closest(".remove-image").length) return
        $input.trigger("click")
      })

      // Drag & drop behavior
      $area.on("dragover", (e) => {
        e.preventDefault()
        const dt = e.originalEvent && e.originalEvent.dataTransfer
        if (dt) dt.dropEffect = "copy"
        $area.addClass("dragover")
      })

      $area.on("dragleave", (e) => {
        e.preventDefault()
        $area.removeClass("dragover")
      })

      $area.on("drop", (e) => {
        e.preventDefault()
        $area.removeClass("dragover")
        const files = e.originalEvent && e.originalEvent.dataTransfer && e.originalEvent.dataTransfer.files
        if (files && files[0]) {
          handleFileSelect(files[0], $content, $preview, areaSel, inputSel, previewSel)
        }
      })

      // Change via input
      $input.on("change", (e) => {
        const file = e.target.files && e.target.files[0]
        if (file) {
          handleFileSelect(file, $content, $preview, areaSel, inputSel, previewSel)
        }
      })
    }

    /**
     * Read file and render preview
     */
    function handleFileSelect(file, $content, $preview, areaSel, inputSel, previewSel) {
      // Basic type guard (optional): images only
      if (file && file.type && !/^image\//i.test(file.type)) {
        showWarning(["فایل انتخاب‌شده تصویر نیست"])
        return
      }

      const reader = new FileReader()
      reader.onload = (e) => {
        // Hide helper content; show preview
        $content.css("display", "none")
        $preview
          .html(
            [
              '<img src="',
              e.target.result,
              '" alt="Preview" class="preview-image">',
              '<button type="button" class="remove-image" data-area="',
              areaSel,
              '" data-input="',
              inputSel,
              '" data-preview="',
              previewSel,
              '">',
              '<i class="ri-close-line"></i>',
              "</button>",
            ].join(""),
          )
          .css("display", "block")

        $preview.find(".preview-image").on("click", (e) => {
          e.stopPropagation()
          showImageViewer(e.target.src)
        })
      }
      reader.readAsDataURL(file)
    }

    /**
     * Show pretty validation warning modal
     */
    function showWarning(missingFields) {
      $(".validation-warning").remove() // ensure single instance

      const $overlay = $('<div class="validation-warning"></div>')
      const $box = $('<div class="validation-warning-box"></div>')
      const $icon = $('<div class="warning-icon"><i class="ri-error-warning-line"></i></div>')
      const $title = $('<h3 class="warning-title">فیلدهای الزامی پر نشده‌اند</h3>')
      const $msg = $('<p class="warning-message">لطفاً موارد زیر را کامل کنید:</p>')

      // Correct class names per CSS
      const $list = $('<ul class="missing-fields-list"></ul>')
      ;(missingFields || []).forEach((t) => {
        $list.append("<li>" + String(t) + "</li>")
      })

      const $close = $('<button type="button" class="warning-close-btn">باشه</button>')

      $close.on("click", () => {
        $overlay.removeClass("show")
        setTimeout(() => {
          $overlay.remove()
        }, 200)
      })

      $box.append($icon, $title, $msg, $list, $close)
      $overlay.append($box)
      $("body").append($overlay)

      // trigger fade-in (assumes .validation-warning.show { opacity:1; ... })
      requestAnimationFrame(() => {
        $overlay.addClass("show")
      })
    }

    function showGuidanceModal() {
      const $modal = $("#guidanceModal")
      if (!$modal.length) return

      requestAnimationFrame(() => {
        $modal.addClass("show")
      })
    }

    function showImageViewer(imageSrc) {
      const $modal = $("#imageViewerModal")
      const $img = $("#viewerImage")

      if (!$modal.length || !$img.length) return

      $img.attr("src", imageSrc)

      requestAnimationFrame(() => {
        $modal.addClass("show")
      })
    }
  })
})(window.jQuery)

      // --- END original file ---
    } else {
      // Page guard: not on the intended page, skip running this file.
    }
  } catch (e) {
    // Swallow errors to avoid breaking the other page's scripts.
    console && console.warn && console.warn('Guarded block failed:', e);
  }
})();

/* ===== END measure.js ===== */



/* ===== BEGIN check.js (original content below; unmodified) ===== */
;(function() {
  try {
    if (typeof document !== 'undefined' && document.querySelector('.check-form')) {
      // --- BEGIN original file (check.js) ---
(($) => {
  $(() => {
    var apiUrl = window.apiUrl || function(path) { return path; };

    // Read upload_id from URL query params
    var urlParams = new URLSearchParams(window.location.search);
    var uploadId = urlParams.get("upload_id");
    var pollTimer = null;

    // Build media URL from the secondary API base (e.g. http://localhost:8001)
    var mediaBase = (window.API_CONFIG && window.API_CONFIG.BASE_URL_SECONDARY || "").replace(/\/api\/v1\/?$/, "");

    // Display images
    function displayImages(images) {
      if (images[0]) $("#checkImage1").attr("src", mediaBase + images[0]);
      if (images[1]) $("#checkImage2").attr("src", mediaBase + images[1]);
      if (images[2]) $("#checkImage3").attr("src", mediaBase + images[2]);
    }

    // Display parameters
    function displayParameters(params) {
      $("#param-height").text(params.height || 0);
      $("#param-weight").text(params.weight || 0);
      $("#param-chest").text(params.chest || 0);
      $("#param-waist").text(params.waist || 0);
      $("#param-hips").text(params.hips || 0);
      $("#param-arm").text(params.arm || 0);
      $("#param-thigh").text(params.thigh || 0);
      $("#param-calf").text(params.calf || 0);
      $("#param-neck").text(params.neck || 0);
      $("#param-arm-length").text(params["arm-length"] || 0);
      $("#param-leg-length").text(params["leg-length"] || 0);
    }

    // Map backend measurement keys to frontend display keys
    function mapMeasurements(avg) {
      return {
        height: Math.round(avg.user_height_cm || 0),
        weight: Math.round(avg.user_weight_kg || 0),
        chest: Math.round(avg.chest_circum_cm || 0),
        waist: Math.round(avg.waist_circum_cm || 0),
        hips: Math.round(avg.hip_circum_cm || 0),
        arm: Math.round(avg.upperarm_circum_cm || 0),
        thigh: Math.round(avg.thigh_circum_cm || 0),
        calf: Math.round(avg.calf_circum_cm || 0),
        neck: Math.round(avg.neck_circum_cm || 0),
        "arm-length": Math.round(avg.sleeve_len_cm || 0),
        "leg-length": Math.round(avg.pants_outseam_cm || 0),
      };
    }

    // Show/hide a loading overlay on the check page
    function showLoadingOverlay(show, msg) {
      var $overlay = $("#checkLoadingOverlay");
      if (!$overlay.length && show) {
        $overlay = $(
          '<div id="checkLoadingOverlay" class="loading-modal" style="display:flex">' +
            '<div class="loading-content">' +
              '<span class="loader"></span>' +
              '<h3 class="loading-text">' + (msg || "در حال پردازش هوش مصنوعی...") + '</h3>' +
            '</div>' +
          '</div>'
        );
        $("body").append($overlay);
        requestAnimationFrame(function() { $overlay.addClass("show"); });
      }
      if ($overlay.length) {
        if (show) {
          $overlay.find(".loading-text").text(msg || "در حال پردازش هوش مصنوعی...");
          $overlay.addClass("show").css("display", "flex");
        } else {
          $overlay.removeClass("show");
          setTimeout(function() { $overlay.css("display", "none"); }, 300);
        }
      }
    }

    // Show processing status message in parameter values
    function showProcessingStatus(msg) {
      $(".check-form .parameter-value[id^='param-']").text(msg || "...");
    }

    // Poll for results
    function pollResults() {
      if (!uploadId) return;

      var resultsUrl = apiUrl("/uploads/" + uploadId + "/results", "secondary");
      var authHeaders = {};
      var savedToken = localStorage.getItem("auth_token");
      if (savedToken) {
        authHeaders["Authorization"] = "Bearer " + savedToken;
      }

      $.ajax({
        url: resultsUrl,
        method: "GET",
        headers: authHeaders,
        success: function(data) {
          if (data.status === "processing" || data.status === "pending") {
            showLoadingOverlay(true, "در حال پردازش هوش مصنوعی...");
            showProcessingStatus("...");
            pollTimer = setTimeout(pollResults, 4000);
          } else if (data.status === "completed" || data.status === "completed_with_errors") {
            showLoadingOverlay(false);

            // Find the "Average" measurement entry
            var avg = {};
            if (data.measurements && data.measurements.length) {
              for (var i = 0; i < data.measurements.length; i++) {
                if (data.measurements[i].label === "Average") {
                  avg = data.measurements[i].results || {};
                  break;
                }
              }
              // Fallback: use last measurement if no Average found
              if (!Object.keys(avg).length) {
                avg = data.measurements[data.measurements.length - 1].results || {};
              }
            }

            displayParameters(mapMeasurements(avg));

            // Display original upload images
            if (data.original_images && data.original_images.length) {
              displayImages(data.original_images);
            } else if (data.processed_urls && data.processed_urls.length) {
              displayImages(data.processed_urls);
            }
          } else {
            showLoadingOverlay(false);
            showProcessingStatus("خطا در پردازش");
          }
        },
        error: function() {
          showProcessingStatus("...");
          pollTimer = setTimeout(pollResults, 4000);
        }
      });
    }

    // Load data from backend
    function loadDataFromBackend() {
      if (uploadId) {
        showLoadingOverlay(true, "در حال پردازش هوش مصنوعی...");
        showProcessingStatus("...");
        pollResults();
      } else {
        // No upload_id — show zeros
        displayParameters({
          height: 0, weight: 0, chest: 0, waist: 0, hips: 0,
          arm: 0, thigh: 0, calf: 0, neck: 0, "arm-length": 0, "leg-length": 0
        });
      }
    }

    // Open edit modal
    $("#openEditModal").on("click", () => {
      // Populate modal with current values
      $("#edit-height").val($("#param-height").text());
      $("#edit-weight").val($("#param-weight").text());
      $("#edit-chest").val($("#param-chest").text());
      $("#edit-waist").val($("#param-waist").text());
      $("#edit-hips").val($("#param-hips").text());
      $("#edit-arm").val($("#param-arm").text());
      $("#edit-thigh").val($("#param-thigh").text());
      $("#edit-calf").val($("#param-calf").text());
      $("#edit-neck").val($("#param-neck").text());
      $("#edit-arm-length").val($("#param-arm-length").text());
      $("#edit-leg-length").val($("#param-leg-length").text());

      // Show modal
      $("#editModal").addClass("show");
    });

    // Close modal
    function closeModal() {
      $("#editModal").removeClass("show");
    }

    $("#closeModal, #cancelModal").on("click", closeModal);

    // Close modal when clicking outside
    $("#editModal").on("click", (e) => {
      if ($(e.target).is("#editModal")) {
        closeModal();
      }
    });

    // Handle form submission
    $("#editForm").on("submit", (e) => {
      e.preventDefault();

      // Get updated values
      const updatedParams = {
        height: $("#edit-height").val(),
        weight: $("#edit-weight").val(),
        chest: $("#edit-chest").val(),
        waist: $("#edit-waist").val(),
        hips: $("#edit-hips").val(),
        arm: $("#edit-arm").val(),
        thigh: $("#edit-thigh").val(),
        calf: $("#edit-calf").val(),
        neck: $("#edit-neck").val(),
        "arm-length": $("#edit-arm-length").val(),
        "leg-length": $("#edit-leg-length").val(),
      };

      displayParameters(updatedParams);
      closeModal();

      // Show success message (optional)
      console.log("Parameters updated:", updatedParams);
      window.location.href = "questions.html?upload_id=" + encodeURIComponent(uploadId)
    });

    // Initialize page
    loadDataFromBackend();
  });
})(window.jQuery);

      // --- END original file ---
    } else {
      // Page guard: not on the intended page, skip running this file.
    }
  } catch (e) {
    // Swallow errors to avoid breaking the other page's scripts.
    console && console.warn && console.warn('Guarded block failed:', e);
  }
})();

/* ===== END check.js ===== */
