let inputTimers = new Map();
let realValues = new Map();
const API_CONFIG = window.API_CONFIG || {};
const API_KEY = API_CONFIG.API_KEY || "";
const apiUrl = window.apiUrl || ((path) => path);

function handleSmartInput($inputElement) {
  const el = $inputElement[0];
  const currentDisplay = $inputElement.val();
  const previousReal = realValues.get(el) || "";

  let newReal = previousReal;

  if (currentDisplay.length < previousReal.length) {
    newReal = previousReal.slice(0, currentDisplay.length);
  } else {
    const newChar = currentDisplay.slice(-1);
    newReal += newChar;
  }

  realValues.set(el, newReal);

  if ($inputElement.attr("data-revealed") !== "true") {
    const display =
      newReal.length > 0
        ? "●".repeat(newReal.length - 1) + newReal.slice(-1)
        : "";
    $inputElement.val(display);

    if (inputTimers.has(el)) {
      clearTimeout(inputTimers.get(el));
    }

    const timeout = setTimeout(() => {
      $inputElement.val("●".repeat(newReal.length));
      inputTimers.delete(el);
    }, 500);

    inputTimers.set(el, timeout);
  } else {
    $inputElement.val(newReal);
  }
}

$(function () {
  const logbtn = $("#subbtn-login");
  const logindiv = $(".log--page");
  const signinemail = $("#sign-in-email");
  const signinpassword = $("#sign-in-password");
  const signinmassage = $("#sign-in-error");
  const eyesignin = $(".eye-icon");
  const eyesiconsignin = $("#eye-icon-sign-in");
  // const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const passwordpattern = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z\d\W_]{8,}$/;

  function showMessage(text, color = "red") {
    signinmassage.html(text);
    signinmassage.css("color", color);
  }

  if (logbtn.length && logindiv.length) {
    logbtn.on("click", function (e) {
      e.preventDefault();

      const emailVal = (signinemail.val() || "").trim();
      const passwordReal = realValues.get(signinpassword[0]) || "";

      // if (!passwordpattern.test((passwordReal || "").trim())) {
      //   showMessage("ایمیل یا رمز اشتباه است.", "red");
      //   return;
      // }

      // UI feedback
      logbtn.prop("disabled", true);
      const originalBtnText = logbtn.text();
      logbtn.text("درحال ارسال...");

      const payload = {
        username: emailVal,
        password: passwordReal
      };

      $.ajax({
        url: apiUrl("/login"),
        method: "POST",
        contentType: "application/json",
        headers: {
          "x-api-key": API_KEY
        },
        data: JSON.stringify(payload),
        dataType: "json",
        timeout: 10000,
        success: function (response) {
          if (response && response.success) {
            // Store auth token for subsequent requests (e.g. uploads to AI service)
            if (response.result && response.result.token) {
              localStorage.setItem("auth_token", response.result.token);
            }
            const redirectUrl = response.redirect || "/upload.html";
            logindiv.css("display", "none");
            window.location.href = redirectUrl;
          } else {
            const msg = (response && response.message) ? response.message : "ایمیل یا رمز اشتباه است.";
            showMessage(msg, "red");
          }
        },
        error: function (jqXHR, textStatus) {
          if (jqXHR && jqXHR.responseJSON && jqXHR.responseJSON.message) {
            showMessage(jqXHR.responseJSON.message, "red");
          } else if (textStatus === 'timeout') {
            showMessage("درخواست تایم‌اوت شد. دوباره تلاش کنید.", "red");
          } else {
            showMessage("خطا در ارتباط با سرور. دوباره تلاش کنید.", "red");
          }
        },
        complete: function () {
          logbtn.prop("disabled", false);
          logbtn.text(originalBtnText);
        }
      });
    });

    if (signinpassword.length) {
      signinpassword.on("input", function () {
        handleSmartInput(signinpassword);
      });
    }

    if (eyesignin.length && eyesiconsignin.length && signinpassword.length) {
      eyesignin.on("click", function () {
        const el = signinpassword[0];
        const currentRealValue = realValues.get(el) || "";

        if (signinpassword.attr("data-revealed") !== "true") {
          signinpassword.val(currentRealValue);
          signinpassword.attr("data-revealed", "true");
          eyesiconsignin.removeClass("ri-eye-fill").addClass("ri-eye-off-fill");
        } else {
          signinpassword.val("●".repeat(currentRealValue.length));
          signinpassword.attr("data-revealed", "false");
          eyesiconsignin.removeClass("ri-eye-off-fill").addClass("ri-eye-fill");
        }
      });
    }
  }
});
