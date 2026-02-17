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
      // displayImages(backendData.images);
      // displayParameters(backendData.parameters);
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
    });

    // Initialize page
    loadDataFromBackend();
  });
})(window.jQuery);
