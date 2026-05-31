const apiUrl = window.apiUrl || ((path) => path);

class QuestionnaireSystem {
  constructor() {
    this.initialQuestions = [];
    this.questions = []; // سوال‌هایی که فعلاً نمایش داده می‌شوند
    this.currentStep = 0;
    this.answers = {};

    // Flow map loaded from /fake.json
    this.flowMap = {};

    // CMS category tree (loaded dynamically)
    this.cmsCategories = [];

    // AI size recommendation cache
    this._sizeRecommendation = null;
    this._sizesLoaded = false;

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

          // After loading static flows, fetch live data from CMS
          this.loadCmsCategories();
          this.loadFacets();
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

  /**
   * Fetch category tree from CMS and inject into questionnaire flows.
   * Replaces the hardcoded garmentType/fabricType options with real
   * sub-categories from the store database.
   */
  loadCmsCategories() {
    var headers = {};
    if (window.API_CONFIG && window.API_CONFIG.API_KEY) {
      headers["x-api-key"] = window.API_CONFIG.API_KEY;
    }
    $.ajax({
      url: apiUrl("/categories/questionnaire", "primary"),
      method: "GET",
      headers: headers,
      dataType: "json",
      timeout: 10000,
    })
      .done((resp) => {
        var cats = resp.data || resp || [];
        if (!Array.isArray(cats) || cats.length === 0) return;
        this.cmsCategories = cats;
        this._injectCmsCategories();
        // Re-render if user is still on step 0
        if (this.currentStep <= 1) this.renderCurrentStep();
      })
      .fail((xhr, status, err) => {
        console.warn("CMS categories unavailable, using static options:", status, err);
      });
  }

  /**
   * Walk the CMS category tree and replace garmentType / fabricType
   * question options in each audience flow.
   *
   * Expected CMS tree example:
   *   [ { slug: "poshak", title: "پوشاک", children: [
   *       { slug: "men", title: "مردانه", children: [
   *           { slug: "shirt", title: "پیراهن" }, ...
   *       ]},
   *       { slug: "women", title: "زنانه", children: [...] },
   *     ]},
   *     { slug: "parche", title: "پارچه", children: [...] },
   *   ]
   */
  _injectCmsCategories() {
    if (!this.cmsCategories.length) return;

    // Keywords to match audience groups to CMS sub-categories
    var audienceKeywords = {
      male:   ["مردانه", "مرد", "men", "male"],
      female: ["زنانه", "زن", "women", "female"],
      kids:   ["بچگانه", "بچه", "کودک", "kids", "children"],
      unisex: ["یونیسکس", "unisex"],
    };

    // Detect which top-level is garment vs fabric
    var garmentCat = null, fabricCat = null;
    for (var i = 0; i < this.cmsCategories.length; i++) {
      var c = this.cmsCategories[i];
      var sl = (c.slug || "").toLowerCase();
      var tl = (c.title || "").toLowerCase();
      if (sl.indexOf("garment") !== -1 || sl.indexOf("poshak") !== -1 ||
          tl.indexOf("پوشاک") !== -1 || tl.indexOf("لباس") !== -1) {
        garmentCat = c;
      } else if (sl.indexOf("fabric") !== -1 || sl.indexOf("parche") !== -1 ||
                 tl.indexOf("پارچه") !== -1) {
        fabricCat = c;
      }
    }

    // Inject garment categories
    if (garmentCat && this.flowMap.garment) {
      this._injectForCategory(garmentCat, "garment", "garmentType", audienceKeywords);
    }

    // Inject fabric categories
    if (fabricCat && this.flowMap.fabric) {
      this._injectForCategory(fabricCat, "fabric", "fabricType", audienceKeywords,
        { male: "male1", female: "female1", kids: "kids1", unisex: "unisex1" });
    }
  }

  /**
   * For a given top-level CMS category, find audience sub-categories
   * and replace the target question's options with real sub-category titles.
   */
  _injectForCategory(cmsCat, flowKey, questionId, audienceKeywords, audienceMap) {
    audienceMap = audienceMap || { male: "male", female: "female", kids: "kids", unisex: "unisex" };
    var children = cmsCat.children || [];

    Object.keys(audienceKeywords).forEach((audience) => {
      var flowAudienceKey = audienceMap[audience];
      if (!this.flowMap[flowKey] || !this.flowMap[flowKey][flowAudienceKey]) return;

      var keywords = audienceKeywords[audience];

      // Find the matching CMS audience sub-category
      var matchedGroup = null;
      for (var i = 0; i < children.length; i++) {
        var child = children[i];
        var title = (child.title || "").toLowerCase();
        var slug  = (child.slug || "").toLowerCase();
        for (var k = 0; k < keywords.length; k++) {
          if (title.indexOf(keywords[k].toLowerCase()) !== -1 ||
              slug.indexOf(keywords[k].toLowerCase()) !== -1) {
            matchedGroup = child;
            break;
          }
        }
        if (matchedGroup) break;
      }

      if (!matchedGroup || !matchedGroup.children || matchedGroup.children.length === 0) return;

      // Build options from the CMS children (these are the actual product types)
      var options = matchedGroup.children.map(function (sub) {
        return { value: sub.slug, label: sub.title };
      });

      // Find the target question in the flow and replace its options
      var flowQuestions = this.flowMap[flowKey][flowAudienceKey];
      for (var q = 0; q < flowQuestions.length; q++) {
        if (flowQuestions[q].id === questionId) {
          flowQuestions[q].options = options;
          // Switch to radio for better UX if there are many options
          if (options.length > 0 && options.length <= 12) {
            flowQuestions[q].type = "radio";
          } else if (options.length > 12) {
            // Too many options — use select dropdown
            flowQuestions[q].type = "select";
            options.unshift({ value: "", label: "انتخاب کنید…" });
          }
          break;
        }
      }
    });

    // Also inject as top-level options if no audience grouping in CMS
    // (e.g. the top-level category directly contains product types without gender split)
    if (children.length > 0) {
      var hasAudienceGroups = false;
      Object.keys(audienceKeywords).forEach(function (aud) {
        var kws = audienceKeywords[aud];
        children.forEach(function (ch) {
          var t = (ch.title || "").toLowerCase();
          var s = (ch.slug || "").toLowerCase();
          kws.forEach(function (kw) {
            if (t.indexOf(kw.toLowerCase()) !== -1 || s.indexOf(kw.toLowerCase()) !== -1) {
              hasAudienceGroups = true;
            }
          });
        });
      });

      // If CMS has no audience grouping, inject all children into all audience flows
      if (!hasAudienceGroups) {
        var opts = children.map(function (sub) {
          return { value: sub.slug, label: sub.title };
        });
        Object.keys(audienceMap).forEach((aud) => {
          var fk = audienceMap[aud];
          if (!this.flowMap[flowKey] || !this.flowMap[flowKey][fk]) return;
          var fqs = this.flowMap[flowKey][fk];
          for (var q = 0; q < fqs.length; q++) {
            if (fqs[q].id === questionId) {
              fqs[q].options = opts.slice();
              break;
            }
          }
        });
      }
    }
  }

  /**
   * Load available sizes from CMS for a given category slug,
   * then fetch AI size recommendation from the Python backend.
   */
  loadDynamicSizes(categorySlug) {
    if (!categorySlug) return;

    this._sizesLoaded = false;
    this._sizeRecommendation = null;

    var headers = {};
    if (window.API_CONFIG && window.API_CONFIG.API_KEY) {
      headers["x-api-key"] = window.API_CONFIG.API_KEY;
    }

    $.ajax({
      url: apiUrl("/categories/" + encodeURIComponent(categorySlug) + "/sizes", "primary"),
      method: "GET",
      headers: headers,
      dataType: "json",
      timeout: 10000,
    })
      .done((resp) => {
        var sizes = (resp && resp.data) || [];
        if (!Array.isArray(sizes) || sizes.length === 0) {
          console.warn("No sizes found for category:", categorySlug);
          return;
        }

        // Update the size question options in all relevant flows
        this._updateSizeOptions(sizes);
        this._sizesLoaded = true;

        // Re-render if user is currently on the size question
        var currentQ = this.questions[this.currentStep];
        if (currentQ && currentQ.id === "size") {
          this.renderCurrentStep();
        }

        // Now fetch AI recommendation
        this._fetchSizeRecommendation(sizes.map(function (s) { return s.value; }));
      })
      .fail(function (xhr, status, err) {
        console.warn("Failed to load sizes from CMS:", status, err);
      });
  }

  /**
   * Replace size question options in the current question flow.
   */
  _updateSizeOptions(sizeOptions) {
    // Update in the active questions array
    for (var i = 0; i < this.questions.length; i++) {
      if (this.questions[i].id === "size") {
        var opts = [{ value: "", label: "انتخاب کنید…" }].concat(sizeOptions);
        this.questions[i].options = opts;
        this.questions[i].type = sizeOptions.length <= 10 ? "radio" : "select";
        break;
      }
    }

    // Also update in flowMap so rebuilds preserve the dynamic sizes
    if (this.flowMap) {
      var self = this;
      Object.keys(this.flowMap).forEach(function (flowKey) {
        var flow = self.flowMap[flowKey];
        if (Array.isArray(flow)) {
          self._updateSizeInArray(flow, sizeOptions);
        } else if (typeof flow === "object") {
          Object.keys(flow).forEach(function (subKey) {
            if (Array.isArray(flow[subKey])) {
              self._updateSizeInArray(flow[subKey], sizeOptions);
            }
          });
        }
      });
    }
  }

  _updateSizeInArray(questionsArray, sizeOptions) {
    for (var i = 0; i < questionsArray.length; i++) {
      if (questionsArray[i].id === "size") {
        var opts = [{ value: "", label: "انتخاب کنید…" }].concat(sizeOptions);
        questionsArray[i].options = opts;
        questionsArray[i].type = sizeOptions.length <= 10 ? "radio" : "select";
        break;
      }
    }
  }

  /**
   * Load dynamic facet values (style, occasion, season) from the CMS.
   * Replaces static options in all flows with real database values.
   */
  loadFacets() {
    var headers = {};
    if (window.API_CONFIG && window.API_CONFIG.API_KEY) {
      headers["x-api-key"] = window.API_CONFIG.API_KEY;
    }

    var self = this;
    $.ajax({
      url: apiUrl("/products/facets?fields=style,occasion,season", "primary"),
      method: "GET",
      headers: headers,
      dataType: "json",
      timeout: 10000,
    })
      .done(function (resp) {
        var data = resp && resp.data ? resp.data : {};
        if (data.style && data.style.length > 0) {
          self._injectFacetOptions("style", data.style);
        }
        if (data.occasion && data.occasion.length > 0) {
          self._injectFacetOptions("occasion", data.occasion);
        }
        if (data.season && data.season.length > 0) {
          self._injectFacetOptions("season", data.season);
        }
        // Re-render if user is still on an early step
        if (self.currentStep <= 2) self.renderCurrentStep();
      })
      .fail(function (xhr, status, err) {
        console.warn("CMS facets unavailable, using static options:", status, err);
      });
  }

  /**
   * Replace options for a given question ID across all flows.
   */
  _injectFacetOptions(questionId, options) {
    var self = this;

    // Update active questions
    for (var i = 0; i < this.questions.length; i++) {
      if (this.questions[i].id === questionId) {
        this.questions[i].options = options;
        if (options.length <= 8) {
          // Use checkbox for style (multi-select), radio for others
          this.questions[i].type = (questionId === "style") ? "checkbox" : "radio";
        } else {
          this.questions[i].type = "select";
          if (options[0] && options[0].value !== "") {
            options.unshift({ value: "", label: "انتخاب کنید…" });
          }
        }
        break;
      }
    }

    // Update in flowMap so rebuilds also get dynamic values
    if (!this.flowMap) return;
    Object.keys(this.flowMap).forEach(function (flowKey) {
      var flow = self.flowMap[flowKey];
      if (Array.isArray(flow)) {
        self._injectFacetInArray(flow, questionId, options);
      } else if (typeof flow === "object") {
        Object.keys(flow).forEach(function (subKey) {
          if (Array.isArray(flow[subKey])) {
            self._injectFacetInArray(flow[subKey], questionId, options);
          }
        });
      }
    });
  }

  _injectFacetInArray(questionsArray, questionId, options) {
    for (var i = 0; i < questionsArray.length; i++) {
      if (questionsArray[i].id === questionId) {
        questionsArray[i].options = options.slice();
        if (options.length <= 8) {
          questionsArray[i].type = (questionId === "style") ? "checkbox" : "radio";
        } else {
          questionsArray[i].type = "select";
        }
        break;
      }
    }
  }

  /**
   * Fetch AI size recommendation from the Python backend.
   */
  _fetchSizeRecommendation(availableSizes) {
    var urlParams = new URLSearchParams(window.location.search);
    var uploadId = urlParams.get("upload_id");
    if (!uploadId || !availableSizes || availableSizes.length === 0) return;

    var authHeaders = { "Content-Type": "application/json" };
    var savedToken = localStorage.getItem("auth_token");
    if (savedToken) {
      authHeaders["Authorization"] = "Bearer " + savedToken;
    }

    var self = this;
    $.ajax({
      url: apiUrl("/recommendations/size-recommendation", "secondary"),
      method: "POST",
      headers: authHeaders,
      contentType: "application/json",
      data: JSON.stringify({
        upload_id: uploadId,
        available_sizes: availableSizes,
      }),
      dataType: "json",
      timeout: 15000,
    })
      .done(function (resp) {
        self._sizeRecommendation = resp;
        // Re-render if user is on the size question
        var currentQ = self.questions[self.currentStep];
        if (currentQ && currentQ.id === "size") {
          self.renderCurrentStep();
        }
      })
      .fail(function (xhr, status, err) {
        console.warn("Failed to get size recommendation:", status, err);
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

    if (!categoryValue || !this.flowMap || !this.flowMap[categoryValue]) {
      return base;
    }

    const flowEntry = this.flowMap[categoryValue];

    // If flowEntry is an array, use it directly
    if (Array.isArray(flowEntry)) {
      return base.concat(flowEntry.map((q) => Object.assign({}, q)));
    }

    // If flowEntry is an object with gender sub-keys, add a gender question
    if (typeof flowEntry === "object") {
      const genderKeys = Object.keys(flowEntry);
      const genderQuestion = {
        id: "_audience",
        label: "برای چه کسی می‌خواهید؟",
        type: "radio",
        required: true,
        options: genderKeys.map((k) => {
          const labels = {
            male: "مردانه", female: "زنانه", kids: "بچه‌گانه", unisex: "یونیسکس",
            male1: "مردانه", female1: "زنانه", kids1: "بچه‌گانه", unisex1: "یونیسکس",
          };
          return { value: k, label: labels[k] || k };
        }),
      };
      const withGender = base.concat([genderQuestion]);

      // If audience already answered, append the sub-flow questions
      const audience = this.answers["_audience"];
      if (audience && Array.isArray(flowEntry[audience])) {
        return withGender.concat(flowEntry[audience].map((q) => Object.assign({}, q)));
      }
      return withGender;
    }

    return base;
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
    console.log(this.questions);
    
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

    // Show AI size recommendation banner for the size question
    if (question.id === "size" && this._sizeRecommendation && this._sizeRecommendation.recommended_size) {
      var rec = this._sizeRecommendation;
      var confLabel = rec.confidence === "high" ? "اطمینان بالا" : (rec.confidence === "medium" ? "اطمینان متوسط" : "تقریبی");
      var confClass = rec.confidence === "high" ? "high" : (rec.confidence === "medium" ? "medium" : "low");
      html += `<div class="ai-size-recommendation ${confClass}">`;
      html += `<div class="ai-rec-icon">&#x1F4D0;</div>`;
      html += `<div class="ai-rec-content">`;
      html += `<strong>پیشنهاد هوش مصنوعی: سایز ${rec.recommended_size}</strong>`;
      html += `<span class="ai-rec-confidence">(${confLabel})</span>`;
      if (rec.details) {
        var parts = [];
        if (rec.details.chest) parts.push("سینه: " + rec.details.chest);
        if (rec.details.waist) parts.push("کمر: " + rec.details.waist);
        if (rec.details.hip) parts.push("باسن: " + rec.details.hip);
        if (parts.length > 0) {
          html += `<div class="ai-rec-details">${parts.join(" | ")}</div>`;
        }
      }
      html += `<div class="ai-rec-note">شما می‌توانید سایز دیگری انتخاب کنید</div>`;
      html += `</div></div>`;
    }

    switch (question.type) {
      case "radio":
        html += `<div class="options-container">`;
        question.options.forEach((option) => {
          var isRecommended = question.id === "size" &&
            this._sizeRecommendation &&
            this._sizeRecommendation.recommended_size &&
            option.value &&
            option.value.toUpperCase() === this._sizeRecommendation.recommended_size.toUpperCase();
          var extraClass = isRecommended ? " ai-recommended" : "";
          var badge = isRecommended ? '<span class="ai-badge">AI</span>' : "";
          html += `
            <label class="option-item${extraClass}">
              <input type="radio" name="${question.id}" value="${option.value}" />
              <span class="option-label">${option.label}${badge}</span>
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

    // Auto-select AI recommended size if no saved answer yet
    if (savedAnswer == null && question.id === "size" && this._sizeRecommendation && this._sizeRecommendation.recommended_size) {
      var rec = this._sizeRecommendation.recommended_size;
      if (question.type === "radio") {
        this.$questionContainer
          .find(`input[type="radio"][name="size"][value="${rec}"]`)
          .prop("checked", true);
      } else if (question.type === "select") {
        this.$questionContainer.find(`select[name="size"]`).val(rec);
      }
      return;
    }

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

    // When user selects garmentType or fabricType, load dynamic sizes
    if (question.id === "garmentType" || question.id === "fabricType") {
      this.loadDynamicSizes(answer);
    }

    // Handle category or audience selection: rebuild the question flow
    if (question.id === "category" || question.id === "_audience") {
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

    // When the user selects an audience (gender), rebuild flow to include sub-flow questions
    $(document).on("change", "input[name='_audience']", (e) => {
      const val = $(e.currentTarget).val();
      this.answers["_audience"] = val;
      const newQuestions = this.rebuildQuestionsForCategory(this.answers["category"]);
      const allowedIds = newQuestions.map((q) => q.id);
      this.pruneAnswers(allowedIds);
      this.questions = newQuestions;
      // Move to next question after audience selection
      const audienceIdx = this.questions.findIndex((q) => q.id === "_audience");
      if (audienceIdx >= 0 && audienceIdx < this.questions.length - 1) {
        this.currentStep = audienceIdx + 1;
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
