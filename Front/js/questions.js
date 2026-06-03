const apiUrl = window.apiUrl || ((path) => path);

class QuestionnaireSystem {
  constructor() {
    this.questions = [];
    this.currentStep = 0;
    this.answers = {};

    // CMS category tree (loaded dynamically)
    this.categoryTree = [];
    // Fallback flows from fake.json (used only if CMS is unreachable)
    this.fallbackInitial = [];
    this.fallbackFlows = {};
    this.useFallback = false;

    // ── Multi-product mode state ──
    this._multiMode = false;
    this._selectedTypes = [];      // [{slug, label}, ...]
    this._activeTypeIdx = 0;       // which product type is being configured
    this._typeAttrStep = 0;        // current attribute step within active type
    this._perTypeFacets = {};      // slug → {size:[…], style:[…], …}
    this._perTypeQuestions = {};    // slug → [question, …]
    this._perTypeAnswers = {};     // slug → {size:"M", style:[…], …}
    this._perTypeSizeRec = {};     // slug → AI size rec object
    this._facetsLoadingCount = 0;

    // Loading state
    this._isLoading = false;

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

    // Show loading while category tree loads
    this._showLoading("در حال بارگذاری دسته‌بندی‌ها...");

    // Load category tree from CMS, with fake.json as fallback
    this._loadCategoryTree();
  }

  // ══════════════ Data Loading ══════════════

  _loadCategoryTree() {
    var self = this;
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
      .done(function (resp) {
        var cats = resp.data || resp || [];
        if (Array.isArray(cats) && cats.length > 0) {
          self.categoryTree = cats;
          self.useFallback = false;
          self._hideLoading();
          self._buildDynamicQuestions();
          self.renderCurrentStep();
        } else {
          self._loadFallback();
        }
      })
      .fail(function () {
        self._loadFallback();
      });
  }

  _loadFallback() {
    var self = this;
    $.ajax({ url: "/fake.json", method: "GET", dataType: "json", cache: false })
      .done(function (data) {
        self.useFallback = true;
        if (Array.isArray(data.initial)) {
          self.fallbackInitial = data.initial.map(function (q) { return Object.assign({}, q); });
        } else {
          self._initFallbackDefaults();
        }
        if (data.flows && typeof data.flows === "object") {
          self.fallbackFlows = data.flows;
        }
        self._hideLoading();
        self._buildDynamicQuestions();
        self.renderCurrentStep();
      })
      .fail(function () {
        self._initFallbackDefaults();
        self.useFallback = true;
        self._hideLoading();
        self._buildDynamicQuestions();
        self.renderCurrentStep();
        self.showError("عدم امکان بارگذاری داده");
      });
  }

  _initFallbackDefaults() {
    this.fallbackInitial = [
      {
        id: "category", label: "چه چیزی می‌خواهید؟", type: "radio", required: true,
        options: [
          { value: "garment", label: "پوشاک" },
          { value: "fabric", label: "پارچه" },
        ],
      },
    ];
  }

  // ══════════════ Question Building ══════════════

  _buildDynamicQuestions() {
    if (this.useFallback) {
      this._buildFromFallback();
      return;
    }
    this._buildFromCategoryTree();
  }

  /**
   * Build base questions from the CMS category tree.
   *
   * Step 1: Top-level categories (Clothing / Fabric)
   * Step 2: Children of selected (Men / Women / Kids / Unisex)
   * Step 3: Grandchildren (Pants / Shirt / Coat / ...) — MULTI-SELECT
   *
   * Attribute questions (Step 4+) are NOT added here.
   * They are built per-product-type in multi-product mode.
   */
  _buildFromCategoryTree() {
    var questions = [];

    // ── Step 1: Main category ──
    var serviceKeywords = ["خدمات", "service", "خدمت"];
    var topCats = this.categoryTree.filter(function (c) {
      var t = (c.title || "").toLowerCase();
      var s = (c.slug || "").toLowerCase();
      for (var i = 0; i < serviceKeywords.length; i++) {
        if (t.indexOf(serviceKeywords[i]) !== -1 || s.indexOf(serviceKeywords[i]) !== -1) return false;
      }
      return true;
    });

    questions.push({
      id: "category",
      label: "چه چیزی می‌خواهید؟",
      type: "radio",
      required: true,
      options: topCats.map(function (c) {
        return { value: c.slug, label: c.title };
      }),
    });

    // ── Step 2: Audience / gender ──
    var selectedCatSlug = this.answers["category"];
    var selectedCat = selectedCatSlug ? this._findInTree(this.categoryTree, selectedCatSlug) : null;

    if (selectedCat && selectedCat.children && selectedCat.children.length > 0) {
      questions.push({
        id: "_audience",
        label: "برای چه کسی می‌خواهید؟",
        type: "radio",
        required: true,
        options: selectedCat.children.map(function (c) {
          return { value: c.slug, label: c.title };
        }),
      });
    }

    // ── Step 3: Product types — MULTI-SELECT ──
    var selectedAudience = this._getSelectedAudience();

    if (selectedAudience && selectedAudience.children && selectedAudience.children.length > 0) {
      var isFabric = this._isFabricCategory(selectedCat);
      var typeQuestionId = isFabric ? "fabricTypes" : "garmentTypes";
      questions.push({
        id: typeQuestionId,
        label: "نوع محصولات مورد نظر خود را انتخاب کنید (می‌توانید چند مورد انتخاب کنید)",
        type: "checkbox",
        required: true,
        options: selectedAudience.children.map(function (c) {
          return { value: c.slug, label: c.title };
        }),
      });
    }

    this.questions = questions;
  }

  /**
   * Build attribute questions for a specific product type using its facets data.
   */
  _buildAttributeQuestionsForType(typeSlug, facetsData) {
    var questions = [];
    var isFabric = this._isFabricCategory(
      this._findInTree(this.categoryTree, this.answers["category"])
    );
    var data = facetsData || {};

    // Size (always first if available)
    if (data.size && data.size.length > 0) {
      var sizeOpts = data.size.slice();
      questions.push({
        id: "size",
        label: "سایز خود را انتخاب کنید",
        type: sizeOpts.length <= 10 ? "radio" : "select",
        required: true,
        options: sizeOpts.length > 10
          ? [{ value: "", label: "انتخاب کنید…" }].concat(sizeOpts)
          : sizeOpts,
      });
    }

    // Garment attributes
    if (!isFabric) {
      if (data.style && data.style.length > 0) {
        questions.push({
          id: "style", label: "استایل ترجیحی شما چیست؟",
          type: "checkbox", required: false,
          options: data.style,
        });
      }
      if (data.occasion && data.occasion.length > 0) {
        questions.push({
          id: "occasion", label: "برای چه مناسبتی می‌خواهید؟",
          type: "checkbox", required: false,
          options: data.occasion,
        });
      }
      if (data.season && data.season.length > 0) {
        questions.push({
          id: "season", label: "برای چه فصلی می‌خواهید؟",
          type: data.season.length <= 6 ? "radio" : "checkbox", required: false,
          options: data.season,
        });
      }
    }

    // Colors (both garment and fabric)
    if (data.color && data.color.length > 0) {
      questions.push({
        id: "colors", label: "رنگ‌های مورد علاقه خود را انتخاب کنید",
        type: "checkbox", required: false,
        options: data.color,
      });
    }

    // Fabric-specific attributes
    if (isFabric) {
      if (data.pattern && data.pattern.length > 0) {
        questions.push({
          id: "pattern", label: "طرح پارچه مورد نظر را انتخاب کنید",
          type: "radio", required: false,
          options: data.pattern,
        });
      }
      if (data.usage && data.usage.length > 0) {
        questions.push({
          id: "usage", label: "کاربرد پارچه را انتخاب کنید",
          type: "checkbox", required: false,
          options: data.usage,
        });
      }
      if (data.occasion && data.occasion.length > 0) {
        questions.push({
          id: "occasion", label: "برای چه مناسبتی پارچه را می‌خواهید؟",
          type: "checkbox", required: false,
          options: data.occasion,
        });
      }
      if (data.season && data.season.length > 0) {
        questions.push({
          id: "season", label: "فصل مورد نظر برای استفاده از پارچه",
          type: data.season.length <= 6 ? "radio" : "checkbox", required: false,
          options: data.season,
        });
      }
      if (data.weave && data.weave.length > 0) {
        questions.push({
          id: "weave", label: "ویژگی‌های بافت پارچه",
          type: "checkbox", required: false,
          options: data.weave,
        });
      }
      if (data.material && data.material.length > 0) {
        questions.push({
          id: "material", label: "جنس پارچه",
          type: "radio", required: false,
          options: data.material,
        });
      }
    }

    return questions;
  }

  /**
   * Build questions from fallback fake.json (old flow system).
   */
  _buildFromFallback() {
    var base = this.fallbackInitial.map(function (q) { return Object.assign({}, q); });
    var categoryVal = this.answers["category"];

    if (!categoryVal || !this.fallbackFlows[categoryVal]) {
      this.questions = base;
      return;
    }

    var flowEntry = this.fallbackFlows[categoryVal];

    if (Array.isArray(flowEntry)) {
      this.questions = base.concat(flowEntry.map(function (q) { return Object.assign({}, q); }));
      return;
    }

    if (typeof flowEntry === "object") {
      var genderKeys = Object.keys(flowEntry);
      var labels = {
        male: "مردانه", female: "زنانه", kids: "بچه‌گانه", unisex: "یونیسکس",
        male1: "مردانه", female1: "زنانه", kids1: "بچه‌گانه", unisex1: "یونیسکس",
      };
      var genderQuestion = {
        id: "_audience", label: "برای چه کسی می‌خواهید؟",
        type: "radio", required: true,
        options: genderKeys.map(function (k) { return { value: k, label: labels[k] || k }; }),
      };
      var withGender = base.concat([genderQuestion]);

      var audience = this.answers["_audience"];
      if (audience && Array.isArray(flowEntry[audience])) {
        this.questions = withGender.concat(flowEntry[audience].map(function (q) { return Object.assign({}, q); }));
      } else {
        this.questions = withGender;
      }
    }
  }

  // ══════════════ Category Tree Helpers ══════════════

  _findInTree(tree, slug) {
    if (!tree || !slug) return null;
    for (var i = 0; i < tree.length; i++) {
      if (tree[i].slug === slug) return tree[i];
      var found = this._findInTree(tree[i].children || [], slug);
      if (found) return found;
    }
    return null;
  }

  _findInChildren(children, slug) {
    if (!children) return null;
    for (var i = 0; i < children.length; i++) {
      if (children[i].slug === slug) return children[i];
    }
    return null;
  }

  _isFabricCategory(cat) {
    if (!cat) return false;
    var s = (cat.slug || "").toLowerCase();
    var t = (cat.title || "").toLowerCase();
    return s.indexOf("fabric") !== -1 || s.indexOf("parche") !== -1 ||
           t.indexOf("پارچه") !== -1;
  }

  _getSelectedAudience() {
    var selectedCatSlug = this.answers["category"];
    var selectedCat = selectedCatSlug ? this._findInTree(this.categoryTree, selectedCatSlug) : null;
    var selectedAudienceSlug = this.answers["_audience"];
    return selectedAudienceSlug && selectedCat
      ? this._findInChildren(selectedCat.children, selectedAudienceSlug)
      : null;
  }

  _mapCategoryForBackend(slug) {
    var cat = this._findInTree(this.categoryTree, slug);
    if (!cat) return slug;
    if (this._isFabricCategory(cat)) return "fabric";
    return "garment";
  }

  // ══════════════ Loading State ══════════════

  _showLoading(message) {
    this._isLoading = true;
    this.$questionContainer.addClass("is-loading");
    this.$backBtn.prop("disabled", true);
    this.$nextBtn.prop("disabled", true);

    this.$questionContainer.find(".q-loading-overlay").remove();

    var overlay = $('<div class="q-loading-overlay">' +
      '<div class="q-spinner"></div>' +
      '<div class="q-loading-text">' + (message || "در حال بارگذاری...") + '</div>' +
      '</div>');
    this.$questionContainer.append(overlay);
  }

  _hideLoading() {
    this._isLoading = false;
    this.$questionContainer.removeClass("is-loading");
    this.$questionContainer.find(".q-loading-overlay").remove();
  }

  // ══════════════ Multi-Product Mode ══════════════

  _enterMultiProductMode(selectedSlugs) {
    var self = this;
    var selectedAudience = this._getSelectedAudience();

    // Build selected types list with labels
    this._selectedTypes = selectedSlugs.map(function (slug) {
      var child = selectedAudience ? self._findInChildren(selectedAudience.children, slug) : null;
      return { slug: slug, label: child ? child.title : slug };
    });

    this._multiMode = true;
    this._activeTypeIdx = 0;
    this._typeAttrStep = 0;
    this._perTypeFacets = {};
    this._perTypeQuestions = {};
    // Preserve any previously entered per-type answers (in case user went back)
    var oldAnswers = this._perTypeAnswers || {};
    this._perTypeAnswers = {};
    for (var i = 0; i < this._selectedTypes.length; i++) {
      var slug = this._selectedTypes[i].slug;
      this._perTypeAnswers[slug] = oldAnswers[slug] || {};
    }
    this._perTypeSizeRec = {};

    this._loadAllTypeFacets();
  }

  _loadAllTypeFacets() {
    var self = this;
    this._facetsLoadingCount = this._selectedTypes.length;
    this._showLoading("در حال بارگذاری ویژگی‌های محصولات...");

    var headers = {};
    if (window.API_CONFIG && window.API_CONFIG.API_KEY) {
      headers["x-api-key"] = window.API_CONFIG.API_KEY;
    }

    var allFields = "size,style,occasion,season,color,pattern,usage,weave,material";

    this._selectedTypes.forEach(function (typeInfo) {
      var slug = typeInfo.slug;
      var url = apiUrl("/products/facets?fields=" + allFields + "&category=" + encodeURIComponent(slug), "primary");

      $.ajax({
        url: url,
        method: "GET",
        headers: headers,
        dataType: "json",
        timeout: 10000,
      })
        .done(function (resp) {
          var data = (resp && resp.data) ? resp.data : {};
          self._perTypeFacets[slug] = data;
          self._perTypeQuestions[slug] = self._buildAttributeQuestionsForType(slug, data);
        })
        .fail(function () {
          console.warn("Failed to load facets for:", slug);
          self._perTypeFacets[slug] = {};
          self._perTypeQuestions[slug] = [];
        })
        .always(function () {
          self._facetsLoadingCount--;
          if (self._facetsLoadingCount <= 0) {
            self._hideLoading();
            self._onAllFacetsLoaded();
          }
        });
    });
  }

  _onAllFacetsLoaded() {
    this._activeTypeIdx = 0;
    this._typeAttrStep = 0;

    // Find first type that actually has questions
    for (var i = 0; i < this._selectedTypes.length; i++) {
      var slug = this._selectedTypes[i].slug;
      var qs = this._perTypeQuestions[slug] || [];
      if (qs.length > 0) {
        this._activeTypeIdx = i;
        break;
      }
    }

    // Check if all types have zero questions → go straight to summary
    var allEmpty = this._selectedTypes.every(function (t) {
      return (this._perTypeQuestions[t.slug] || []).length === 0;
    }.bind(this));

    if (allEmpty) {
      this.showSummary();
      return;
    }

    // Fetch AI size recommendations for all types that have sizes
    this._fetchAllSizeRecommendations();

    this._renderMultiProductStep();
  }

  _fetchAllSizeRecommendations() {
    var self = this;
    var urlParams = new URLSearchParams(window.location.search);
    var uploadId = urlParams.get("upload_id");
    if (!uploadId) return;

    var authHeaders = { "Content-Type": "application/json" };
    var savedToken = localStorage.getItem("auth_token");
    if (savedToken) {
      authHeaders["Authorization"] = "Bearer " + savedToken;
    }

    this._selectedTypes.forEach(function (typeInfo) {
      var slug = typeInfo.slug;
      var facets = self._perTypeFacets[slug] || {};
      var sizes = (facets.size || []).map(function (s) { return s.value; });
      if (sizes.length === 0) return;

      $.ajax({
        url: apiUrl("/recommendations/size-recommendation", "secondary"),
        method: "POST",
        headers: authHeaders,
        contentType: "application/json",
        data: JSON.stringify({ upload_id: uploadId, available_sizes: sizes }),
        dataType: "json",
        timeout: 15000,
      })
        .done(function (resp) {
          self._perTypeSizeRec[slug] = resp;
          // Re-render if currently showing this type's size question
          var activeType = self._selectedTypes[self._activeTypeIdx];
          if (activeType && activeType.slug === slug) {
            var questions = self._perTypeQuestions[slug] || [];
            var currentQ = questions[self._typeAttrStep];
            if (currentQ && currentQ.id === "size") {
              self._renderMultiProductStep();
            }
          }
        })
        .fail(function () { /* ignore */ });
    });
  }

  _resetMultiProductState() {
    this._multiMode = false;
    this._selectedTypes = [];
    this._activeTypeIdx = 0;
    this._typeAttrStep = 0;
    this._perTypeFacets = {};
    this._perTypeQuestions = {};
    this._perTypeAnswers = {};
    this._perTypeSizeRec = {};
    this._facetsLoadingCount = 0;
  }

  // ══════════════ Rendering ══════════════

  renderCurrentStep() {
    if (this._multiMode) {
      this._renderMultiProductStep();
      return;
    }

    this.hideError();
    this.$summarySection.hide();
    this.$questionContainer.show();
    this.$backBtn.show();
    this.$nextBtn.show();

    if (!this.questions || this.questions.length === 0) {
      this.$stepLabel.text("در حال بارگذاری...");
      this.$progressBar.css("width", "0%");
      this.$questionContainer.html(
        '<div class="question-wrapper"><div class="ai-rec-loading"><span class="spinner"></span><p>در حال دریافت اطلاعات...</p></div></div>'
      );
      this.$backBtn.prop("disabled", true);
      this.$nextBtn.prop("disabled", true);
      return;
    }

    if (this.currentStep < 0) this.currentStep = 0;
    if (this.currentStep > this.questions.length - 1)
      this.currentStep = this.questions.length - 1;

    var question = this.questions[this.currentStep];
    var totalSteps = this.questions.length;

    this.$stepLabel.text("مرحله " + (this.currentStep + 1) + " از " + totalSteps);
    this.$progressBar.css("width", ((this.currentStep + 1) / totalSteps) * 100 + "%");

    this.$questionContainer.html(this.buildQuestionHTML(question));

    this.$backBtn.prop("disabled", this.currentStep === 0);
    this.$nextBtn.prop("disabled", false);

    // Last base step button text
    var isProductTypeStep = question.id === "garmentTypes" || question.id === "fabricTypes";
    if (isProductTypeStep) {
      this.$nextBtn.text("ادامه تنظیمات محصولات");
    } else if (this.currentStep === totalSteps - 1 && totalSteps > 1) {
      this.$nextBtn.text("اتمام و مشاهده خلاصه");
    } else {
      this.$nextBtn.text("بعدی");
    }

    this.restoreSavedAnswer(question);
  }

  _renderMultiProductStep() {
    this.hideError();
    this.$summarySection.hide();
    this.$questionContainer.show();
    this.$backBtn.show();
    this.$nextBtn.show();

    var activeType = this._selectedTypes[this._activeTypeIdx];
    if (!activeType) return;

    var questions = this._perTypeQuestions[activeType.slug] || [];

    // ── Progress calculation ──
    var totalAttrSteps = 0;
    var completedAttrSteps = 0;
    var self = this;
    this._selectedTypes.forEach(function (t, idx) {
      var tq = self._perTypeQuestions[t.slug] || [];
      totalAttrSteps += Math.max(tq.length, 1);
      if (idx < self._activeTypeIdx) {
        completedAttrSteps += Math.max(tq.length, 1);
      } else if (idx === self._activeTypeIdx) {
        completedAttrSteps += self._typeAttrStep;
      }
    });
    var baseSteps = this.questions.length;
    var totalProgress = baseSteps + totalAttrSteps;
    var currentProgress = baseSteps + completedAttrSteps;

    var attrLabel = questions.length > 0
      ? " — ویژگی " + (this._typeAttrStep + 1) + " از " + questions.length
      : "";
    this.$stepLabel.text(activeType.label + attrLabel);
    this.$progressBar.css("width", ((currentProgress + 1) / totalProgress) * 100 + "%");

    // ── Build pills + question HTML ──
    var html = this._buildProductTypePillsHTML();

    if (questions.length === 0) {
      html += '<div class="question-wrapper">' +
        '<div class="empty-state">ویژگی خاصی برای «' + activeType.label + '» یافت نشد. ادامه دهید.</div>' +
        '</div>';
    } else if (this._typeAttrStep < questions.length) {
      var question = questions[this._typeAttrStep];
      // Temporarily set size recommendation for this type
      var currentSizeRec = this._perTypeSizeRec[activeType.slug] || null;
      html += this._buildQuestionHTMLWithSizeRec(question, currentSizeRec);
    }

    this.$questionContainer.html(html);

    // Attach pill click handlers
    this._attachPillHandlers();

    // Restore saved answer for this type
    if (questions.length > 0 && this._typeAttrStep < questions.length) {
      this._restoreMultiAnswer(activeType.slug, questions[this._typeAttrStep]);
    }

    // ── Button states ──
    this.$backBtn.prop("disabled", false);

    // Show "finish" text only if this is the last attr of the last type
    // AND all other types are already completed
    var isLastStepHere = (questions.length === 0 || this._typeAttrStep >= questions.length - 1);
    var allOthersComplete = true;
    for (var oi = 0; oi < this._selectedTypes.length; oi++) {
      if (oi === this._activeTypeIdx) continue;
      if (!this._isTypeCompleted(oi)) { allOthersComplete = false; break; }
    }
    var showFinish = isLastStepHere && allOthersComplete;
    this.$nextBtn.text(showFinish ? "اتمام و مشاهده خلاصه" : "بعدی");
    this.$nextBtn.prop("disabled", false);
  }

  _buildProductTypePillsHTML() {
    var html = '<div class="product-type-pills">';
    var self = this;

    this._selectedTypes.forEach(function (t, idx) {
      var isActive = idx === self._activeTypeIdx;
      var isCompleted = self._isTypeCompleted(idx);
      var cls = "product-type-pill";
      if (isActive) cls += " active";
      else if (isCompleted) cls += " completed";

      var icon = isCompleted && !isActive
        ? '<span class="pill-check">&#10003;</span>'
        : '<span class="pill-number">' + (idx + 1) + '</span>';

      html += '<div class="' + cls + '" data-type-idx="' + idx + '">';
      html += icon;
      html += '<span class="pill-label">' + t.label + '</span>';
      html += '</div>';
    });

    html += '</div>';
    return html;
  }

  _isTypeCompleted(typeIdx) {
    if (typeIdx >= this._selectedTypes.length) return false;
    var slug = this._selectedTypes[typeIdx].slug;
    var questions = this._perTypeQuestions[slug] || [];
    // No questions → auto-completed
    if (questions.length === 0) return true;
    // Check that all required questions have answers
    var typeAnswers = this._perTypeAnswers[slug] || {};
    for (var i = 0; i < questions.length; i++) {
      var q = questions[i];
      if (q.required) {
        var a = typeAnswers[q.id];
        if (a == null || a === "" || (Array.isArray(a) && a.length === 0)) return false;
      }
    }
    return true;
  }

  _attachPillHandlers() {
    var self = this;
    this.$questionContainer.find(".product-type-pill").on("click", function () {
      var idx = parseInt($(this).data("type-idx"), 10);
      if (isNaN(idx) || idx === self._activeTypeIdx) return;

      // Only allow clicking completed types (to review) or the current one
      // Don't allow jumping forward to unstarted types
      if (!self._isTypeCompleted(idx) && idx > self._activeTypeIdx) return;

      // Save current answer before switching
      self._saveCurrentMultiAnswer();

      self._activeTypeIdx = idx;
      var slug = self._selectedTypes[idx].slug;
      var questions = self._perTypeQuestions[slug] || [];
      // If completed, show first question for review; else find first unanswered
      if (self._isTypeCompleted(idx)) {
        self._typeAttrStep = 0;
      } else {
        self._typeAttrStep = self._findFirstUnansweredStep(idx);
      }
      self._renderMultiProductStep();
    });
  }

  _saveCurrentMultiAnswer() {
    var activeType = this._selectedTypes[this._activeTypeIdx];
    if (!activeType) return;
    var questions = this._perTypeQuestions[activeType.slug] || [];
    if (questions.length === 0 || this._typeAttrStep >= questions.length) return;

    var question = questions[this._typeAttrStep];
    var answer = this.getCurrentAnswer();
    if (answer !== null && answer !== undefined) {
      if (!this._perTypeAnswers[activeType.slug]) {
        this._perTypeAnswers[activeType.slug] = {};
      }
      this._perTypeAnswers[activeType.slug][question.id] = answer;
    }
  }

  _restoreMultiAnswer(typeSlug, question) {
    var answers = this._perTypeAnswers[typeSlug] || {};
    var savedAnswer = answers[question.id];

    // Auto-select AI recommended size if no saved answer yet
    var sizeRec = this._perTypeSizeRec[typeSlug];
    if (savedAnswer == null && question.id === "size" && sizeRec && sizeRec.recommended_size) {
      var rec = sizeRec.recommended_size;
      if (question.type === "radio") {
        this.$questionContainer.find('input[type="radio"][name="size"][value="' + rec + '"]').prop("checked", true);
      } else if (question.type === "select") {
        this.$questionContainer.find('select[name="size"]').val(rec);
      }
      return;
    }

    if (savedAnswer == null) return;

    if (question.type === "radio") {
      this.$questionContainer.find('input[type="radio"][name="' + question.id + '"][value="' + savedAnswer + '"]').prop("checked", true);
    } else if (question.type === "checkbox") {
      var $container = this.$questionContainer;
      (Array.isArray(savedAnswer) ? savedAnswer : []).forEach(function (value) {
        $container.find('input[type="checkbox"][name="' + question.id + '"][value="' + value + '"]').prop("checked", true);
      });
    } else if (question.type === "select") {
      this.$questionContainer.find('select[name="' + question.id + '"]').val(savedAnswer);
    } else {
      this.$questionContainer.find('input[name="' + question.id + '"], textarea[name="' + question.id + '"]').val(savedAnswer);
    }
  }

  // ══════════════ HTML Building ══════════════

  buildQuestionHTML(question) {
    return this._buildQuestionHTMLWithSizeRec(question, null);
  }

  _buildQuestionHTMLWithSizeRec(question, sizeRec) {
    var html = '<div class="question-wrapper">';
    html += '<label class="question-label">' + question.label +
      (question.required ? ' <span class="required">*</span>' : '') + '</label>';

    // AI size recommendation banner
    if (question.id === "size" && sizeRec && sizeRec.recommended_size) {
      var rec = sizeRec;
      var confLabel = rec.confidence === "high" ? "اطمینان بالا" : (rec.confidence === "medium" ? "اطمینان متوسط" : "تقریبی");
      var confClass = rec.confidence === "high" ? "high" : (rec.confidence === "medium" ? "medium" : "low");
      html += '<div class="ai-size-recommendation ' + confClass + '">';
      html += '<div class="ai-rec-icon">&#x1F4D0;</div>';
      html += '<div class="ai-rec-content">';
      html += '<strong>پیشنهاد هوش مصنوعی: سایز ' + rec.recommended_size + '</strong>';
      html += '<span class="ai-rec-confidence">(' + confLabel + ')</span>';
      if (rec.details) {
        var parts = [];
        if (rec.details.chest) parts.push("سینه: " + rec.details.chest);
        if (rec.details.waist) parts.push("کمر: " + rec.details.waist);
        if (rec.details.hip) parts.push("باسن: " + rec.details.hip);
        if (parts.length > 0) {
          html += '<div class="ai-rec-details">' + parts.join(" | ") + '</div>';
        }
      }
      html += '<div class="ai-rec-note">شما می‌توانید سایز دیگری انتخاب کنید</div>';
      html += '</div></div>';
    }

    switch (question.type) {
      case "radio":
        html += '<div class="options-container">';
        var self = this;
        (question.options || []).forEach(function (option) {
          var isRecommended = question.id === "size" && sizeRec && sizeRec.recommended_size &&
            option.value && option.value.toUpperCase() === sizeRec.recommended_size.toUpperCase();
          var extraClass = isRecommended ? " ai-recommended" : "";
          var badge = isRecommended ? '<span class="ai-badge">AI</span>' : "";
          html += '<label class="option-item' + extraClass + '">' +
            '<input type="radio" name="' + question.id + '" value="' + option.value + '" />' +
            '<span class="option-label">' + option.label + badge + '</span></label>';
        });
        html += '</div>';
        break;

      case "checkbox":
        html += '<div class="options-container">';
        (question.options || []).forEach(function (option) {
          html += '<label class="option-item">' +
            '<input type="checkbox" name="' + question.id + '" value="' + option.value + '" />' +
            '<span class="option-label">' + option.label + '</span></label>';
        });
        html += '</div>';
        break;

      case "select":
        html += '<select name="' + question.id + '" class="select-input">';
        (question.options || []).forEach(function (option) {
          html += '<option value="' + option.value + '">' + option.label + '</option>';
        });
        html += '</select>';
        break;

      case "text":
        html += '<input type="text" name="' + question.id + '" class="text-input" placeholder="' + (question.placeholder || "") + '" />';
        break;

      case "number":
        html += '<input type="number" name="' + question.id + '" class="text-input"' +
          (question.min != null ? ' min="' + question.min + '"' : '') +
          (question.max != null ? ' max="' + question.max + '"' : '') + ' />';
        break;

      default:
        html += '<div>نوع سوال پشتیبانی نشده: ' + question.type + '</div>';
    }

    html += '</div>';
    return html;
  }

  restoreSavedAnswer(question) {
    var savedAnswer = this.answers[question.id];
    if (savedAnswer == null) return;

    if (question.type === "radio") {
      this.$questionContainer.find('input[type="radio"][name="' + question.id + '"][value="' + savedAnswer + '"]').prop("checked", true);
    } else if (question.type === "checkbox") {
      var $container = this.$questionContainer;
      (Array.isArray(savedAnswer) ? savedAnswer : []).forEach(function (value) {
        $container.find('input[type="checkbox"][name="' + question.id + '"][value="' + value + '"]').prop("checked", true);
      });
    } else if (question.type === "select") {
      this.$questionContainer.find('select[name="' + question.id + '"]').val(savedAnswer);
    } else {
      this.$questionContainer.find('input[name="' + question.id + '"], textarea[name="' + question.id + '"]').val(savedAnswer);
    }
  }

  // ══════════════ Answer Handling ══════════════

  getCurrentAnswer() {
    var question;
    if (this._multiMode) {
      var activeType = this._selectedTypes[this._activeTypeIdx];
      if (!activeType) return null;
      var questions = this._perTypeQuestions[activeType.slug] || [];
      question = questions[this._typeAttrStep];
    } else {
      question = this.questions[this.currentStep];
    }
    if (!question) return null;

    if (question.type === "radio") {
      var $checked = this.$questionContainer.find('input[type="radio"][name="' + question.id + '"]:checked');
      return $checked.length ? $checked.val() : null;
    } else if (question.type === "checkbox") {
      return this.$questionContainer.find('input[type="checkbox"][name="' + question.id + '"]:checked')
        .map(function () { return $(this).val(); }).get();
    } else if (question.type === "select") {
      return this.$questionContainer.find('select[name="' + question.id + '"]').val();
    } else {
      var value = this.$questionContainer.find('input[name="' + question.id + '"], textarea[name="' + question.id + '"]').val();
      return value ? value.trim() : null;
    }
  }

  validateAnswer(answer) {
    var question;
    if (this._multiMode) {
      var activeType = this._selectedTypes[this._activeTypeIdx];
      if (!activeType) return null;
      var questions = this._perTypeQuestions[activeType.slug] || [];
      question = questions[this._typeAttrStep];
    } else {
      question = this.questions[this.currentStep];
    }
    if (!question) return null;

    if (question.required) {
      if (question.type === "checkbox") {
        if (!answer || answer.length === 0) return "لطفاً حداقل یک مورد را انتخاب کنید.";
      } else if (!answer || answer === "") {
        return "این فیلد الزامی است.";
      }
    }
    if (question.type === "number" && answer) {
      var num = Number(answer);
      if (question.min != null && num < question.min) return "مقدار باید حداقل " + question.min + " باشد.";
      if (question.max != null && num > question.max) return "مقدار باید حداکثر " + question.max + " باشد.";
    }
    return null;
  }

  showError(message) { this.$errorMessage.text(message).show(); }
  hideError() { this.$errorMessage.hide(); }

  // ══════════════ Navigation ══════════════

  handleNext() {
    if (this._isLoading) return;

    // ── Multi-product mode navigation ──
    if (this._multiMode) {
      this._handleMultiNext();
      return;
    }

    var answer = this.getCurrentAnswer();
    var error = this.validateAnswer(answer);
    if (error) { this.showError(error); return; }

    var question = this.questions[this.currentStep];
    this.answers[question.id] = answer;

    // Category changed → clear downstream
    if (question.id === "category") {
      delete this.answers["_audience"];
      delete this.answers["garmentTypes"];
      delete this.answers["fabricTypes"];
      this._resetMultiProductState();
      this._buildDynamicQuestions();
      this.currentStep++;
      this.renderCurrentStep();
      return;
    }

    // Audience changed → clear product types
    if (question.id === "_audience") {
      delete this.answers["garmentTypes"];
      delete this.answers["fabricTypes"];
      this._resetMultiProductState();
      this._buildDynamicQuestions();
      this.currentStep++;
      this.renderCurrentStep();
      return;
    }

    // Product type step (multi-select) → enter multi-product mode
    if (question.id === "garmentTypes" || question.id === "fabricTypes") {
      var selectedSlugs = Array.isArray(answer) ? answer : [answer];
      if (selectedSlugs.length === 0) {
        this.showError("لطفاً حداقل یک نوع محصول را انتخاب کنید.");
        return;
      }
      this.answers[question.id] = selectedSlugs;
      this._enterMultiProductMode(selectedSlugs);
      return;
    }

    // Fallback mode flow rebuilds
    if (this.useFallback && (question.id === "category" || question.id === "_audience")) {
      this._buildDynamicQuestions();
      if (this.currentStep >= this.questions.length - 1) {
        this.showSummary();
      } else {
        this.currentStep++;
        this.renderCurrentStep();
      }
      return;
    }

    // Last question
    if (this.currentStep === this.questions.length - 1) {
      this.showSummary();
      return;
    }

    this.currentStep++;
    this.renderCurrentStep();
  }

  _handleMultiNext() {
    var activeType = this._selectedTypes[this._activeTypeIdx];
    if (!activeType) return;

    var questions = this._perTypeQuestions[activeType.slug] || [];

    // Validate and save current answer if there are questions
    if (questions.length > 0 && this._typeAttrStep < questions.length) {
      var answer = this.getCurrentAnswer();
      var error = this.validateAnswer(answer);
      if (error) { this.showError(error); return; }

      if (!this._perTypeAnswers[activeType.slug]) {
        this._perTypeAnswers[activeType.slug] = {};
      }
      this._perTypeAnswers[activeType.slug][questions[this._typeAttrStep].id] = answer;

      // Advance within this type
      if (this._typeAttrStep < questions.length - 1) {
        this._typeAttrStep++;
        this._renderMultiProductStep();
        return;
      }
    }

    // Current type done → find next incomplete type
    var nextIdx = this._findNextIncompleteType(this._activeTypeIdx + 1);
    if (nextIdx !== -1) {
      this._activeTypeIdx = nextIdx;
      this._typeAttrStep = 0;
      // Skip types with no questions automatically
      var nextQuestions = this._perTypeQuestions[this._selectedTypes[nextIdx].slug] || [];
      if (nextQuestions.length === 0) {
        // This type auto-completes, try next again
        this._handleMultiNext();
        return;
      }
      this._renderMultiProductStep();
      return;
    }

    // All types complete — verify before showing summary
    if (this._allTypesCompleted()) {
      this.showSummary();
    } else {
      // Jump to first incomplete type
      var firstIncomplete = this._findNextIncompleteType(0);
      if (firstIncomplete !== -1) {
        this._activeTypeIdx = firstIncomplete;
        this._typeAttrStep = this._findFirstUnansweredStep(firstIncomplete);
        this._renderMultiProductStep();
        this.showError("لطفاً ابتدا تمام بخش‌ها را تکمیل کنید.");
      } else {
        this.showSummary();
      }
    }
  }

  _findNextIncompleteType(startIdx) {
    for (var i = startIdx; i < this._selectedTypes.length; i++) {
      if (!this._isTypeCompleted(i)) return i;
    }
    return -1;
  }

  _findFirstUnansweredStep(typeIdx) {
    var slug = this._selectedTypes[typeIdx].slug;
    var questions = this._perTypeQuestions[slug] || [];
    var typeAnswers = this._perTypeAnswers[slug] || {};
    for (var i = 0; i < questions.length; i++) {
      var q = questions[i];
      if (q.required) {
        var a = typeAnswers[q.id];
        if (a == null || a === "" || (Array.isArray(a) && a.length === 0)) return i;
      }
    }
    return 0;
  }

  _allTypesCompleted() {
    for (var i = 0; i < this._selectedTypes.length; i++) {
      if (!this._isTypeCompleted(i)) return false;
    }
    return true;
  }

  handleBack() {
    if (this._isLoading) return;

    if (this._multiMode) {
      this._handleMultiBack();
      return;
    }

    if (this.currentStep > 0) {
      this.currentStep--;
      this.renderCurrentStep();
    }
  }

  _handleMultiBack() {
    // Save current answer before going back
    this._saveCurrentMultiAnswer();

    // Go back within current type
    if (this._typeAttrStep > 0) {
      this._typeAttrStep--;
      this._renderMultiProductStep();
      return;
    }

    // Go to previous type's last attribute
    if (this._activeTypeIdx > 0) {
      this._activeTypeIdx--;
      var prevType = this._selectedTypes[this._activeTypeIdx];
      var prevQuestions = this._perTypeQuestions[prevType.slug] || [];
      this._typeAttrStep = Math.max(0, prevQuestions.length - 1);
      this._renderMultiProductStep();
      return;
    }

    // Exit multi-product mode, go back to product type selection step
    this._multiMode = false;
    this.renderCurrentStep();
  }

  // ══════════════ Summary & Submit ══════════════

  showSummary() {
    this.$questionContainer.hide();
    this.$backBtn.hide();
    this.$nextBtn.hide();
    this.$summarySection.show();
    this.$stepLabel.text("خلاصه پاسخ‌ها");
    this.$progressBar.css("width", "100%");

    var html = "";
    var self = this;

    // Base questions (category, audience, product types)
    this.questions.forEach(function (question) {
      var answer = self.answers[question.id];
      var displayAnswer = self._formatAnswerForDisplay(question, answer);

      html += '<div class="answer-item">' +
        '<div class="answer-question">' + question.label + '</div>' +
        '<div class="answer-value">' + (displayAnswer || "-") + '</div></div>';
    });

    // Per-product-type answers
    if (this._multiMode && this._selectedTypes.length > 0) {
      this._selectedTypes.forEach(function (typeInfo) {
        html += '<div class="answer-group-header">' +
          '<span class="answer-group-icon">&#9654;</span> ' +
          typeInfo.label + '</div>';

        var typeQuestions = self._perTypeQuestions[typeInfo.slug] || [];
        var typeAnswers = self._perTypeAnswers[typeInfo.slug] || {};

        if (typeQuestions.length === 0) {
          html += '<div class="answer-item"><div class="answer-value" style="color:#999;">ویژگی خاصی تعریف نشده</div></div>';
        } else {
          typeQuestions.forEach(function (q) {
            var answer = typeAnswers[q.id];
            var displayAnswer = self._formatAnswerForDisplay(q, answer);
            html += '<div class="answer-item answer-item-indented">' +
              '<div class="answer-question">' + q.label + '</div>' +
              '<div class="answer-value">' + (displayAnswer || "-") + '</div></div>';
          });
        }
      });
    }

    this.$answersList.html(html);
  }

  _formatAnswerForDisplay(question, answer) {
    if (answer == null) return "-";
    if (Array.isArray(answer)) {
      var labels = answer.map(function (val) {
        var option = question.options ? question.options.find(function (opt) { return opt.value === val; }) : null;
        return option ? option.label : val;
      });
      return labels.join("، ");
    } else {
      if (question.options) {
        var option = question.options.find(function (opt) { return opt.value === answer; });
        return option ? option.label : answer;
      }
      return answer;
    }
  }

  handleEdit() {
    this.$questionContainer.show();
    this.$backBtn.show();
    this.$nextBtn.show();
    this.$summarySection.hide();

    if (this._multiMode) {
      // Go back to the last type's last attribute for review
      this._activeTypeIdx = this._selectedTypes.length - 1;
      var lastQuestions = this._perTypeQuestions[this._selectedTypes[this._activeTypeIdx].slug] || [];
      this._typeAttrStep = Math.max(0, lastQuestions.length - 1);
      this._renderMultiProductStep();
    } else {
      this.currentStep = 0;
      this.renderCurrentStep();
    }
  }

  handleSubmit() {
    var urlParams = new URLSearchParams(window.location.search);
    var uploadId = urlParams.get("upload_id");

    // Prepare answers for the backend
    var submittedAnswers = Object.assign({}, this.answers);
    if (!this.useFallback && submittedAnswers.category) {
      submittedAnswers.category = this._mapCategoryForBackend(submittedAnswers.category);
    }

    // Add per-product answers in multi-product mode
    if (this._multiMode && this._selectedTypes.length > 0) {
      submittedAnswers.productAnswers = {};
      for (var i = 0; i < this._selectedTypes.length; i++) {
        var slug = this._selectedTypes[i].slug;
        submittedAnswers.productAnswers[slug] = Object.assign({}, this._perTypeAnswers[slug] || {});
      }
    }

    var jsonData = {
      completedAt: new Date().toISOString(),
      answers: submittedAnswers,
    };
    if (uploadId) {
      jsonData.upload_id = uploadId;
    }

    var authHeaders = {};
    var savedToken = localStorage.getItem("auth_token");
    if (savedToken) {
      authHeaders["Authorization"] = "Bearer " + savedToken;
    }

    var self = this;
    var backendCategory = submittedAnswers.category || "";

    $.ajax({
      url: apiUrl("/uploads/questionnaire", "secondary"),
      method: "POST",
      headers: authHeaders,
      contentType: "application/json",
      data: JSON.stringify(jsonData),
      dataType: "json",
    })
      .done(function (response) {
        var recUploadId = (response && response.upload_id) || uploadId || "";
        if (backendCategory === "fabric") {
          // Show processing screen and wait for AI to finish
          self._showProcessingScreen(recUploadId, authHeaders);
        } else {
          window.location.href = "recommendations.html?upload_id=" + encodeURIComponent(recUploadId);
        }
      })
      .fail(function (xhr, status, error) {
        console.error("Submit error:", status, error);
        alert("خطا در ارسال اطلاعات. لطفاً دوباره تلاش کنید.");
      });
  }

  _showProcessingScreen(uploadId, authHeaders) {
    this.$summarySection.hide();
    this.$questionContainer.hide();
    this.$backBtn.hide();
    this.$nextBtn.hide();

    var $overlay = $('<div id="processingOverlay" class="processing-overlay">' +
      '<div class="processing-content">' +
        '<div class="processing-spinner"></div>' +
        '<h3 class="processing-title">در حال پردازش هوش مصنوعی</h3>' +
        '<p class="processing-message">لطفاً صبر کنید، سیستم در حال تحلیل اطلاعات شما و آماده‌سازی پیشنهادات است...</p>' +
        '<div class="processing-progress">' +
          '<div class="processing-progress-bar"></div>' +
        '</div>' +
        '<p class="processing-status" id="processingStatus">در حال شروع پردازش...</p>' +
      '</div>' +
    '</div>');

    $("body").append($overlay);
    this._pollProcessingStatus(uploadId, authHeaders);
  }

  _pollProcessingStatus(uploadId, authHeaders) {
    var self = this;
    var attempts = 0;
    var maxAttempts = 120;
    var $status = $("#processingStatus");
    var $bar = $(".processing-progress-bar");

    var statusMessages = [
      "در حال شروع پردازش...",
      "در حال تحلیل اندازه‌های بدن...",
      "در حال بررسی ترجیحات شما...",
      "در حال جستجوی محصولات مناسب...",
      "در حال تولید پیشنهادات هوشمند...",
      "تقریباً آماده است..."
    ];

    function updateProgress() {
      var pct = Math.min(90, (attempts / maxAttempts) * 100);
      $bar.css("width", pct + "%");
      var msgIdx = Math.min(Math.floor(attempts / 5), statusMessages.length - 1);
      $status.text(statusMessages[msgIdx]);
    }

    function poll() {
      attempts++;
      updateProgress();

      if (attempts > maxAttempts) {
        self._showProcessingError("زمان پردازش بیش از حد طول کشید. لطفاً دوباره تلاش کنید.", uploadId, authHeaders);
        return;
      }

      $.ajax({
        url: apiUrl("/recommendations", "secondary"),
        method: "POST",
        headers: authHeaders,
        contentType: "application/json",
        data: JSON.stringify({ upload_id: uploadId }),
        dataType: "json",
        timeout: 60000,
      })
        .done(function (data) {
          if (data && data.products && data.products.length > 0) {
            $bar.css("width", "100%");
            $status.text("پردازش تکمیل شد! در حال انتقال...");
            try {
              sessionStorage.setItem("fabric_recommendations", JSON.stringify(data));
            } catch (e) { /* ignore */ }
            setTimeout(function () {
              window.location.href = "ShowFabrics.html?upload_id=" + encodeURIComponent(uploadId);
            }, 800);
          } else {
            setTimeout(poll, 2000);
          }
        })
        .fail(function (xhr) {
          if (xhr.status === 404 || xhr.status === 401) {
            self._showProcessingError("خطا در احراز هویت یا یافتن اطلاعات آپلود.", uploadId, authHeaders);
            return;
          }
          setTimeout(poll, 2000);
        });
    }

    setTimeout(poll, 1500);
  }

  _showProcessingError(message, uploadId, authHeaders) {
    var self = this;
    var $overlay = $("#processingOverlay");
    $overlay.find(".processing-content").html(
      '<div class="processing-error-icon">&#10007;</div>' +
      '<h3 class="processing-title" style="color:#e74c3c;">' + message + '</h3>' +
      '<button class="btn-primary processing-retry-btn" id="retryProcessing">' +
        '<i class="ri-refresh-line"></i> تلاش مجدد' +
      '</button>' +
      '<button class="btn-outline processing-back-btn" id="backToQuestions">' +
        'بازگشت به پرسشنامه' +
      '</button>'
    );

    $overlay.on("click", "#retryProcessing", function () {
      $overlay.remove();
      self._showProcessingScreen(uploadId, authHeaders);
    });

    $overlay.on("click", "#backToQuestions", function () {
      $overlay.remove();
      self.$summarySection.show();
    });
  }

  // ══════════════ Event Listeners ══════════════

  attachEventListeners() {
    var self = this;

    this.$nextBtn.on("click", function () { self.handleNext(); });
    this.$backBtn.on("click", function () { self.handleBack(); });
    this.$editBtn.on("click", function () { self.handleEdit(); });
    this.$submitBtn.on("click", function () { self.handleSubmit(); });

    // Auto-advance on category selection
    $(document).on("change", "input[name='category']", function (e) {
      if (self._isLoading) return;
      var val = $(e.currentTarget).val();
      self.answers["category"] = val;
      delete self.answers["_audience"];
      delete self.answers["garmentTypes"];
      delete self.answers["fabricTypes"];
      self._resetMultiProductState();
      self._buildDynamicQuestions();

      if (self.currentStep === 0 && self.questions.length > 1) {
        self.currentStep = 1;
      }
      self.renderCurrentStep();
    });

    // Auto-advance on audience selection
    $(document).on("change", "input[name='_audience']", function (e) {
      if (self._isLoading) return;
      var val = $(e.currentTarget).val();
      self.answers["_audience"] = val;
      delete self.answers["garmentTypes"];
      delete self.answers["fabricTypes"];
      self._resetMultiProductState();
      self._buildDynamicQuestions();

      var audienceIdx = self.questions.findIndex(function (q) { return q.id === "_audience"; });
      if (audienceIdx >= 0 && audienceIdx < self.questions.length - 1) {
        self.currentStep = audienceIdx + 1;
      }
      self.renderCurrentStep();
    });

    // Keyboard navigation
    $(document).on("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        if (!$(document.activeElement).is("textarea") && self.$summarySection.is(":hidden")) {
          e.preventDefault();
          self.handleNext();
        }
      } else if (e.key === "Enter" && e.shiftKey) {
        e.preventDefault();
        self.handleBack();
      }
    });
  }
}

$(function () {
  new QuestionnaireSystem();
});
