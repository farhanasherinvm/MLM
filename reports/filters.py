from django_filters import rest_framework as filters
from level.models import UserLevel
from datetime import date, timedelta

class PaymentFilter(filters.FilterSet):
    status = filters.ChoiceFilter(
        choices=UserLevel._meta.get_field('status').choices
    )
    date_filter = filters.ChoiceFilter(
        method='filter_by_period',
        choices=(
            ('today', 'Today'),
            ('last_week', 'Last Week'),
            ('last_month', 'Last Month'),
        )
    )

    def filter_by_period(self, queryset, name, value):
        today = date.today()

        if value == 'today':
            return queryset.filter(approved_at__date=today)

        elif value == 'last_week':
            start_date = today - timedelta(days=7)
            return queryset.filter(approved_at__date__gte=start_date, approved_at__date__lte=today)

        elif value == 'last_month':
            start_date = today - timedelta(days=30)
            return queryset.filter(approved_at__date__gte=start_date, approved_at__date__lte=today)

        return queryset

    class Meta:
        model = UserLevel
        fields = ['status', 'date_filter']
