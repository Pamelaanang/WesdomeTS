from django.shortcuts import render

# Create your views here.
def design_tester(request):
    # This renders your base.html directly so you can see the CSS/Nav
    return render(request, "base.html")

