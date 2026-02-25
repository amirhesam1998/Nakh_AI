const apiUrl = window.apiUrl || ((path) => path);

class QuestionnaireSystem {
  constructor() {
    this.initialQuestions = [];
    this.questions = []; // سوال‌هایی که فعلاً نمایش داده می‌شوند
    this.currentStep = 0;
    this.answers = {};

    // Flow map loaded from /fake.json
    this.flowMap = {};

    // DOM Elements - using jQuery
    this.$stepLabel = $("#stepLabel");
    this.$progressBar = $("#progressBar");
    this.$questionContainer = $("#questionContainer");
    this.$errorMessage = $("#errorMessage");
    this.$backBtn = $("#backBtn");
    this.$nextBtn = $("#nextBtn");
    this.$summarySection = $("#summarySection");
    this.$answersList = $("#answersList");
    this.$editBtn = $("#editBtn");
    this.$submitBtn = $("#submitBtn");

    this.attachEventListeners();
    this.renderCurrentStep();

    // Load dynamic data from local fake.json using jQuery AJAX
    this.loadFromAjax("/fake.json");
  }

  // Load questions/flows from a local JSON file using jQuery AJAX
  loadFromAjax(url) {
    $.ajax({
      url: url,
      method: "GET",
      dataType: "json",
      cache: false,
    })
      .done((data) => {
        try {
          if (Array.isArray(data.initial)) {
            // نگهداری نسخهٔ اولیه (clone)
            this.initialQuestions = data.initial.map((q) => Object.assign({}, q));
            // نمایش اولیه براساس initial
            this.questions = this.initialQuestions.slice();
          } else {
            // در صورتی که سرور پاسخ ندهد، حداقل از initializeQuestions پیش‌فرض استفاده می‌کنیم
            if (this.initialQuestions.length === 0) this.initializeQuestionsFallback();
            this.questions = this.initialQuestions.slice();
          }

          if (data.flows && typeof data.flows === "object") {
            this.flowMap = data.flows;
          }

          this.currentStep = 0;
          this.answers = {};
          this.renderCurrentStep();
        } catch (e) {
          console.error("Parsing fake.json failed:", e);
          this.showError("خطا در پردازش دادهٔ .");
        }
      })
      .fail((xhr, status, err) => {
        console.error("AJAX error:", status, err);
        this.initializeQuestionsFallback();
        this.questions = this.initialQuestions.slice();
        this.currentStep = 0;
        this.answers = {};
        this.renderCurrentStep();
        this.showError("عدم امکان بارگذاری داده ");
      });
  }

  // Fallback در صورتی که فایل JSON در دسترس نباشد
  initializeQuestionsFallback() {
    this.initialQuestions = [
      {
        id: "category",
        label: "چه چیزی می‌خواهید؟",
        type: "radio",
        required: true,
        options: [
          { value: "garment", label: "پوشاک" },
          { value: "fabric", label: "پارچه" },
        ],
      },
    ];
  }

  // بازسازی سوال‌ها براساس initial + جریان انتخاب‌شده (flowMap)
  rebuildQuestionsForCategory(categoryValue) {
    // همیشه از initialQuestions شروع کن (clone)
    const base = this.initialQuestions.map((q) => Object.assign({}, q));

    if (
      categoryValue &&
      this.flowMap &&
      Array.isArray(this.flowMap[categoryValue])
    ) {
      const flowQuestions = this.flowMap[categoryValue].map((q) =>
        Object.assign({}, q)
      );
      return base.concat(flowQuestions);
    } else {
      return base;
    }
  }

  // حذف پاسخ‌هایی که دیگر مرتبط نیستند
  pruneAnswers(allowedQuestionIds) {
    Object.keys(this.answers).forEach((qid) => {
      if (!allowedQuestionIds.includes(qid)) {
        delete this.answers[qid];
      }
    });
  }

  // Render current step
  renderCurrentStep() {
    this.hideError();
    this.$summarySection.hide();

    // اگر سوالی وجود نداشته باشد، پیام مناسب نشان بده
    if (!this.questions || this.questions.length === 0) {
      this.$stepLabel.text("بدون سوال");
      this.$progressBar.css("width", "0%");
      this.$questionContainer.html(
        '<div class="question-wrapper">سوالی برای نمایش وجود ندارد.</div>'
      );
      this.$backBtn.prop("disabled", true);
      this.$nextBtn.prop("disabled", true);
      return;
    }

    // اطمینان از اینکه currentStep در محدوده است
    if (this.currentStep < 0) this.currentStep = 0;
    if (this.currentStep > this.questions.length - 1)
      this.currentStep = this.questions.length - 1;

    const question = this.questions[this.currentStep];
    const totalSteps = this.questions.length;

    // Update progress
    this.$stepLabel.text(`مرحله ${this.currentStep + 1} از ${totalSteps}`);
    this.$progressBar.css(
      "width",
      `${((this.currentStep + 1) / totalSteps) * 100}%`
    );

    // Render question
    this.$questionContainer.html(this.buildQuestionHTML(question));

    // Update buttons
    this.$backBtn.prop("disabled", this.currentStep === 0);
    this.$nextBtn.prop("disabled", false);
    this.$nextBtn.text(
      this.currentStep === totalSteps - 1 && totalSteps > 1
        ? "اتمام و مشاهده خلاصه"
        : "بعدی"
    );

    // Restore saved answer if exists
    this.restoreSavedAnswer(question);
  }

  // Build HTML for different question types
  buildQuestionHTML(question) {
    let html = `<div class="question-wrapper">`;
    html += `<label class="question-label">${question.label}${
      question.required ? ' <span class="required">*</span>' : ""
    }</label>`;

    switch (question.type) {
      case "radio":
        html += `<div class="options-container">`;
        question.options.forEach((option) => {
          html += `
            <label class="option-item">
              <input type="radio" name="${question.id}" value="${option.value}" />
              <span class="option-label">${option.label}</span>
            </label>
          `;
        });
        html += `</div>`;
        break;

      case "checkbox":
        html += `<div class="options-container">`;
        question.options.forEach((option) => {
          html += `
            <label class="option-item">
              <input type="checkbox" name="${question.id}" value="${option.value}" />
              <span class="option-label">${option.label}</span>
            </label>
          `;
        });
        html += `</div>`;
        break;

      case "select":
        html += `<select name="${question.id}" class="select-input">`;
        // html += `<option value="">-- انتخاب کنید --</option>`;
        question.options.forEach((option) => {
          html += `<option value="${option.value}">${option.label}</option>`;
        });
        html += `</select>`;
        break;

      case "text":
        html += `<input type="text" name="${question.id}" class="text-input" placeholder="${question.placeholder || ""}" />`;
        break;

      case "textarea":
        html += `<textarea name="${question.id}" class="textarea-input" placeholder="${question.placeholder || ""}"></textarea>`;
        break;

      case "number":
        html += `<input type="number" name="${question.id}" class="text-input" ${
          question.min != null ? `min="${question.min}"` : ""
        } ${question.max != null ? `max="${question.max}"` : ""} />`;
        break;

      default:
        html += `<div>نوع سوال پشتیبانی نشده: ${question.type}</div>`;
    }

    html += `</div>`;
    return html;
  }

  // Restore saved answer
  restoreSavedAnswer(question) {
    const savedAnswer = this.answers[question.id];
    if (savedAnswer == null) return;

    if (question.type === "radio") {
      this.$questionContainer
        .find(`input[type="radio"][name="${question.id}"][value="${savedAnswer}"]`)
        .prop("checked", true);
    } else if (question.type === "checkbox") {
      savedAnswer.forEach((value) => {
        this.$questionContainer
          .find(`input[type="checkbox"][name="${question.id}"][value="${value}"]`)
          .prop("checked", true);
      });
    } else if (question.type === "select") {
      this.$questionContainer.find(`select[name="${question.id}"]`).val(savedAnswer);
    } else {
      this.$questionContainer.find(`input[name="${question.id}"], textarea[name="${question.id}"]`).val(savedAnswer);
    }
  }

  // Get current answer
  getCurrentAnswer() {
    const question = this.questions[this.currentStep];

    if (!question) return null;

    if (question.type === "radio") {
      const $checked = this.$questionContainer.find(
        `input[type="radio"][name="${question.id}"]:checked`
      );
      return $checked.length ? $checked.val() : null;
    } else if (question.type === "checkbox") {
      const $checked = this.$questionContainer.find(
        `input[type="checkbox"][name="${question.id}"]:checked`
      );
      return $checked
        .map(function () {
          return $(this).val();
        })
        .get();
    } else if (question.type === "select") {
      return this.$questionContainer.find(`select[name="${question.id}"]`).val();
    } else {
      const value = this.$questionContainer.find(`input[name="${question.id}"], textarea[name="${question.id}"]`).val();
      return value ? value.trim() : null;
    }
  }

  // Validate current answer
  validateAnswer(answer) {
    const question = this.questions[this.currentStep];

    if (question.required) {
      if (question.type === "checkbox") {
        if (!answer || answer.length === 0) {
          return "لطفاً حداقل یک مورد را انتخاب کنید.";
        }
      } else if (!answer || answer === "") {
        return "این فیلد الزامی است.";
      }
    }

    if (question.type === "number" && answer) {
      const num = Number(answer);
      if (question.min != null && num < question.min) {
        return `مقدار باید حداقل ${question.min} باشد.`;
      }
      if (question.max != null && num > question.max) {
        return `مقدار باید حداکثر ${question.max} باشد.`;
      }
    }

    return null;
  }

  // Show error message
  showError(message) {
    this.$errorMessage.text(message).show();
  }

  // Hide error message
  hideError() {
    this.$errorMessage.hide();
  }

  // Handle next button
  handleNext() {
    const answer = this.getCurrentAnswer();
    const error = this.validateAnswer(answer);

    if (error) {
      this.showError(error);
      return;
    }

    // Save answer
    const question = this.questions[this.currentStep];
    this.answers[question.id] = answer;

    // Handle category selection specially: بازسازی جریان بر اساس انتخاب
    if (question.id === "category") {
      const sel = this.answers["category"];
      const newQuestions = this.rebuildQuestionsForCategory(sel);

      // پاکسازی پاسخ‌های نامرتبط
      const allowedIds = newQuestions.map((q) => q.id);
      this.pruneAnswers(allowedIds);

      // جایگزین کن و به سوال بعدی بزن
      this.questions = newQuestions;
      // اگر سوال بعدی وجود نداشت => خلاصه
      if (this.currentStep >= this.questions.length - 1) {
        this.showSummary();
        return;
      } else {
        this.currentStep++;
        this.renderCurrentStep();
        return;
      }
    }

    // Check if this is the last question
    if (this.currentStep === this.questions.length - 1) {
      this.showSummary();
      return;
    }

    // Move to next step
    this.currentStep++;
    this.renderCurrentStep();
  }

  // Handle back button
  handleBack() {
    if (this.currentStep > 0) {
      this.currentStep--;
      this.renderCurrentStep();
    }
  }

  // Show summary
  showSummary() {
    this.$questionContainer.hide();
    this.$backBtn.hide();
    this.$nextBtn.hide();
    this.$summarySection.show();
    this.$stepLabel.text("خلاصه پاسخ‌ها");
    this.$progressBar.css("width", "100%");

    // Build answers list
    let html = "";
    this.questions.forEach((question) => {
      const answer = this.answers[question.id];
      let displayAnswer = "";

      if (Array.isArray(answer)) {
        // Find labels for checkbox answers
        const labels = answer.map((val) => {
          const option = question.options ? question.options.find((opt) => opt.value === val) : null;
          return option ? option.label : val;
        });
        displayAnswer = labels.join("، ");
      } else {
        // Find label for single answer
        if (question.options) {
          const option = question.options.find((opt) => opt.value === answer);
          displayAnswer = option ? option.label : answer;
        } else {
          displayAnswer = answer;
        }
      }

      html += `
        <div class="answer-item">
          <div class="answer-question">${question.label}</div>
          <div class="answer-value">${displayAnswer || "-"}</div>
        </div>
      `;
    });

    this.$answersList.html(html);
  }

  // Handle edit button
  handleEdit() {
    this.$questionContainer.show();
    this.$backBtn.show();
    this.$nextBtn.show();
    this.$summarySection.hide();
    this.currentStep = 0;
    this.renderCurrentStep();
  }

  // Handle submit button - using jQuery AJAX POST
  handleSubmit() {
    // Read upload_id from URL query params
    var urlParams = new URLSearchParams(window.location.search);
    var uploadId = urlParams.get("upload_id");

    const jsonData = {
      completedAt: new Date().toISOString(),
      answers: this.answers,
    };
    if (uploadId) {
      jsonData.upload_id = uploadId;
    }

    // Auth header
    var authHeaders = {};
    var savedToken = localStorage.getItem("auth_token");
    if (savedToken) {
      authHeaders["Authorization"] = "Bearer " + savedToken;
    }

    // Using jQuery AJAX for POST request
    $.ajax({
      url: apiUrl("/uploads/questionnaire", "secondary"),
      method: "POST",
      headers: authHeaders,
      contentType: "application/json",
      data: JSON.stringify(jsonData),
      dataType: "json",
    })
      .done((response) => {
        console.log("Submitted data:", jsonData);
        console.log("Server response:", response);
        // Redirect to recommendations page
        var recUploadId = (response && response.upload_id) || uploadId || "";
        window.location.href = "recommendations.html?upload_id=" + encodeURIComponent(recUploadId);
      })
      .fail((xhr, status, error) => {
        console.error("Submit error:", status, error);
        alert("خطا در ارسال اطلاعات. لطفاً دوباره تلاش کنید.");
        console.log("Data that would be sent:", jsonData);
      });
  }

  // Attach event listeners using jQuery
  attachEventListeners() {
    this.$nextBtn.on("click", () => this.handleNext());
    this.$backBtn.on("click", () => this.handleBack());
    this.$editBtn.on("click", () => this.handleEdit());
    this.$submitBtn.on("click", () => this.handleSubmit());

    // اگر کاربر مستقیماً گزینه category را تغییر داد (بدون زدن Next)، فوراً جریان را بازسازی کن
    $(document).on("change", "input[name='category']", (e) => {
      const val = $(e.currentTarget).val();
      // ذخیرهٔ موقت انتخاب category
      this.answers["category"] = val;
      const newQuestions = this.rebuildQuestionsForCategory(val);
      const allowedIds = newQuestions.map((q) => q.id);
      this.pruneAnswers(allowedIds);
      this.questions = newQuestions;
      // اینجا تصمیم گرفتم کاربر را بعد از انتخاب به سوال بعدی ببرم تا تجربهٔ خطی حفظ شود:
      if (this.currentStep === 0 && this.questions.length > 1) {
        this.currentStep = 1;
      } else {
        // اگر کاربر در مرحله‌ای دیگر است، مطمئن شیم currentStep معتبر است
        if (this.currentStep > this.questions.length - 1) {
          this.currentStep = this.questions.length - 1;
        }
      }
      this.renderCurrentStep();
    });

    // Keyboard navigation using jQuery
    $(document).on("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        const isTextarea = $(document.activeElement).is("textarea");
        if (!isTextarea && this.$summarySection.is(":hidden")) {
          e.preventDefault();
          this.handleNext();
        }
      } else if (e.key === "Enter" && e.shiftKey) {
        e.preventDefault();
        this.handleBack();
      }
    });
  }
}

$(() => {
  new QuestionnaireSystem();
});
