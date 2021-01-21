let forms = document.querySelectorAll("form");
for (let form of forms) {
    form.addEventListener("submit", (event) => {
        // console.log(event)
        let btn = event.submitter;
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status"
                            aria-hidden="true"></span>加载中...`;
    })
}
