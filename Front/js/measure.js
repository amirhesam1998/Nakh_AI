;(($) => {
  $(() => {
    // Initialize upload areas (adjust selectors to match your HTML)
    setupUploadArea("#uploadArea1", "#photo1", "#previewArea1")
    setupUploadArea("#uploadArea2", "#photo2", "#previewArea2")
    setupUploadArea("#uploadArea3", "#photo3", "#previewArea3")

    showGuidanceModal()

    // Hook form submit validation
    const $form = $("form") // or $("#yourFormId") if you have a specific form id
    $form.on("submit", (e) => {
      e.preventDefault()

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

      // All good -> navigate to check.html
      window.location.href = "check.html"
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
