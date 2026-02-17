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

  $.ajax({
    url: API_UPLOAD_URL,
    method: "POST",
    data: formData,
    processData: false,
    contentType: false,
    timeout: 60000,
    success: function (response) {
      const redirectUrl =
        (response && (response.redirect || response.next_url || response.url)) ||
        "check.html"
      window.location.href = redirectUrl
    },
    error: function (jqXHR, textStatus) {
      console.error("Upload error:", textStatus, jqXHR)
      alert("ارور در ارسال داده‌ها رخ داد. لطفاً دوباره تلاش کنید.")
    },
    complete: function () {
      $form.data("submitting", false)
      $loading.removeClass("show").css("display", "none")
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
    // Mock backend data - Replace this with actual API call
    const backendData = {
      images: [
        "./image/image.jpg?key=h67e0",
        "./image/image.jpg?key=3mplr",
        "./image/image.jpg?key=tcshg",
      ],
      parameters: {
        height: 175,
        weight: 70,
        chest: 95,
        waist: 80,
        hips: 98,
        arm: 32,
        thigh: 55,
        calf: 38,
        neck: 38,
        "arm-length": 60,
        "leg-length": 95,
      },
    };

    // Load data from backend
    function loadDataFromBackend() {
      // In production, replace this with actual API call:
      // $.ajax({
      //   url: '/api/check-data',
      //   method: 'GET',
      //   success: function(data) {
      //     displayImages(data.images);
      //     displayParameters(data.parameters);
      //   }
      // });

      // For now, use mock data
      displayImages(backendData.images);
      displayParameters(backendData.parameters);
    }

    // Display images
    function displayImages(images) {
      $("#checkImage1").attr("src", images[0]);
      $("#checkImage2").attr("src", images[1]);
      $("#checkImage3").attr("src", images[2]);
    }

    // Display parameters
    function displayParameters(params) {
      $("#param-height").text(params.height);
      $("#param-weight").text(params.weight);
      $("#param-chest").text(params.chest);
      $("#param-waist").text(params.waist);
      $("#param-hips").text(params.hips);
      $("#param-arm").text(params.arm);
      $("#param-thigh").text(params.thigh);
      $("#param-calf").text(params.calf);
      $("#param-neck").text(params.neck);
      $("#param-arm-length").text(params["arm-length"]);
      $("#param-leg-length").text(params["leg-length"]);
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

      // In production, send to backend:
      // $.ajax({
      //   url: '/api/update-parameters',
      //   method: 'POST',
      //   data: updatedParams,
      //   success: function(response) {
      //     displayParameters(updatedParams);
      //     closeModal();
      //   }
      // });

      // For now, just update the display
      displayParameters(updatedParams);
      closeModal();

      // Show success message (optional)
      console.log("Parameters updated:", updatedParams);
      window.location.href = "questions.html"
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
