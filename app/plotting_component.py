import streamlit as st
import pandas as pd
import os
import io
import zipfile
import numpy as np
import re
from matplotlib_interface import save_plot_to_buffer
from streamlit_sortables import sort_items

# Import the new logic functions
from plotting_logic import (
    check_columns_match,
    is_numerical_column,
    generate_plot_figures,
    generate_combined_plot_logic
)

def render_sorting_controls(df, column_name, key_prefix):
    """Renders a sortable list for categorical column values."""
    with st.expander(f"Sorting of: `{column_name}`", expanded=True):
        
        unique_values_raw = [str(v) for v in df[column_name].unique() if pd.notna(v)]

        # Define a sort key function for numeric-like bins
        def get_bin_sort_key(value):
            match = re.match(r'\[(\d+)', str(value).strip())
            if match:
                return int(match.group(1))
            return -1 # Fallback for non-matching items

        # Check if the first item looks like a bin, e.g., "[2-4]"
        if unique_values_raw and re.match(r'\[\d+', str(unique_values_raw[0]).strip()):
            try:
                # If so, attempt to sort numerically based on the bin's start
                unique_values = sorted(unique_values_raw, key=get_bin_sort_key)
            except (ValueError, TypeError):
                # If sorting fails (e.g., mixed formats), fall back to alphabetical
                unique_values = sorted(unique_values_raw)
        else:
            # Default to standard alphabetical sort
            unique_values = sorted(unique_values_raw)
        
        # Custom CSS for the sortable component
        custom_style = """
            .sortable-item {
                background-color: rgb(240, 242, 246);
                color: black;
                padding: 5px 10px;
                margin-bottom: 4px;
                border-radius: 5px;
                border: 1px solid #DDD;
                width: 100%; /* Force item to take full width */
                box-sizing: border-box; /* Ensure padding doesn't cause overflow */
            }
            .sortable-component > div {
                display: flex;
                flex-direction: column; /* Stack items vertically */
            }
            .sortable-component {
                padding-right: 2rem;
            }
        """
        
        sorted_values = sort_items(
            unique_values, 
            # The key must be unique to the column to force a refresh on change
            key=f"sort_{key_prefix}_{column_name}",
            custom_style=custom_style
        )
        return sorted_values

def render_binning_controls(df, column_name, key_prefix):
    """Renders performant sliders and inputs for numerical binning."""
    st.markdown(f"##### Binning for `{column_name}`")
    min_val = float(df[column_name].min())
    max_val = float(df[column_name].max())

    n_bins_key = f"plot_{key_prefix}_n_bins"
    boundaries_key = f"plot_{key_prefix}_boundaries"

    # Use a callback on the slider to reset boundaries when n_bins changes
    def n_bins_changed():
        n_bins = st.session_state[n_bins_key]
        if n_bins > 0:
            # Calculate new, equally spaced boundaries from min to max
            new_boundaries = np.linspace(min_val, max_val, n_bins + 1)
            st.session_state[boundaries_key] = [round(b, 4) for b in new_boundaries]
        elif boundaries_key in st.session_state:
            # Clear boundaries if n_bins is 0
            del st.session_state[boundaries_key]

    n_bins = st.slider(
        "Number of ranges",
        min_value=1, max_value=10, step=1,
        key=n_bins_key,
        on_change=n_bins_changed,
        value=st.session_state.get(n_bins_key, 1)
    )

    if n_bins < 1:
        return None

    # Ensure boundaries are initialized if they don't exist for the current n_bins
    if boundaries_key not in st.session_state or len(st.session_state.get(boundaries_key, [])) != n_bins + 1:
        n_bins_changed()

    boundaries = st.session_state.get(boundaries_key, [])
    
    st.caption("Fine-tune range delimiters")
    
    is_int = pd.api.types.is_integer_dtype(df[column_name])
    step = 1.0 if is_int else 0.1
    
    num_inputs = n_bins + 1
    new_boundaries = []
    
    # Layout in 2 columns
    cols = st.columns(2)
    
    for i in range(num_inputs):
        with cols[i % 2]:
            val = st.number_input(
                label=f"Delimiter {i+1}",
                value=float(boundaries[i]),
                step=step,
                format="%.4f",
                key=f"{boundaries_key}_input_{i}"
            )
            new_boundaries.append(val)

    # Update session state only if there's a change
    if new_boundaries != boundaries:
        st.session_state[boundaries_key] = new_boundaries
        st.rerun()

    return st.session_state.get(boundaries_key, [])

def render_plotting_component(dataframes, filenames):
    """
    Render the plotting component with controls and visualization
    """
    if not dataframes:
        st.warning("Please select at least one subset to plot")
        return
    
    # Check if column names match across all dataframes
    if not check_columns_match(dataframes):
        st.warning("Please select dataframes with identical column structures")
        return
    
    # Initialize session state for plots
    if 'plots_generated' not in st.session_state:
        st.session_state.plots_generated = False
    
    # Reset button beside the title
    col1, col2 = st.columns([0.9, 0.1])
    with col1:
        st.markdown("#### Plotting Controls")
    with col2:
        if st.button("↺", key="reset_plots"):
            # Full reset of all state variables
            for key in list(st.session_state.keys()):
                if key.startswith("plot_") or key in [
                    "plots_generated", "primary_dim", "secondary_dim", 
                    "y_axis", "show_titles", "comparison_mode", "plot_params",
                    "show_outliers", "fig_size_mode", "fig_width_cm", 
                    "fig_height_cm", "output_format", "plot_titles",
                    "axes_label_mode", "x_axis_label", "y_axis_label",
                    "combine_plots", "combined_plot_title",
                    "grid_layout_mode", "grid_rows", "grid_cols"
                ]:
                    del st.session_state[key]
            st.rerun()
    
    # Get column names from first dataframe
    columns = list(dataframes[0].columns)
    
    # Plot type (disabled for now as we only support boxplots)
    st.selectbox("Plot Type", ["Boxplot"], key="plot_mode", disabled=True)
    
    # Replace multiselect with separate primary and secondary dimension selectors

    col1, col2 = st.columns(2)
    with col1:
        primary_dim = st.selectbox("Primary Dimension", columns, key="primary_dim", 
                                 help="First dimension for grouping (required)")
    with col2:
        # None option for secondary dimension
        secondary_options = ["None"] + columns
        secondary_dim = st.selectbox("Secondary Dimension", secondary_options, key="secondary_dim",
                                   help="Second dimension for coloring (optional)")
    
    # Y-axis selection in its own row
    default_y = "gflops" if "gflops" in columns else columns[0]
    y_axis = st.selectbox("Y-axis", columns, 
                         index=columns.index(default_y) if default_y in columns else 0, 
                         key="y_axis")
    
    # --- Sorting controls for categorical dimensions ---
    primary_dim_order = None
    secondary_dim_order = None

    is_primary_categorical = primary_dim and not is_numerical_column(dataframes[0], primary_dim)
    is_secondary_categorical = secondary_dim not in [None, "None"] and not is_numerical_column(dataframes[0], secondary_dim)

    if is_primary_categorical or is_secondary_categorical:
        col1, col2 = st.columns(2)
        if is_primary_categorical:
            with col1:
                primary_dim_order = render_sorting_controls(dataframes[0], primary_dim, "primary_sort")
        if is_secondary_categorical:
            with col2:
                secondary_dim_order = render_sorting_controls(dataframes[0], secondary_dim, "secondary_sort")

    # --- Binning controls for numerical dimensions ---
    primary_bin_edges = None
    secondary_bin_edges = None

    if primary_dim and is_numerical_column(dataframes[0], primary_dim) and dataframes[0][primary_dim].nunique() > 5:
        primary_bin_edges = render_binning_controls(dataframes[0], primary_dim, "primary")
        st.divider()

    if secondary_dim not in [None, "None"] and is_numerical_column(dataframes[0], secondary_dim) and dataframes[0][secondary_dim].nunique() > 5:
        secondary_bin_edges = render_binning_controls(dataframes[0], secondary_dim, "secondary")
        st.divider()
    
    # Add checkbox for outliers
    show_outliers = st.checkbox("Show outliers", value=False, key="show_outliers")
    
    # Add axes label control
    axes_label_mode = st.segmented_control(
        "Axes Labels",
        ["Auto", "Manual"],
        key="axes_label_mode",
        default="Auto"
    )
    
    # If Manual is selected, add text inputs for X and Y labels
    x_label, y_label = None, None
    if axes_label_mode == "Manual":
        col1, col2 = st.columns(2)
        with col1:
            x_label = st.text_input("X-axis Label", value=primary_dim, key="x_axis_label")
        with col2:
            y_label = st.text_input("Y-axis Label", value=y_axis, key="y_axis_label")
    
    # Comparison mode as segmented control - switch order so Separate is on the left
    comparison_mode = st.segmented_control(
        "Comparison Mode", 
        ["Separate", "Side by Side"],  # Changed order here
        key="comparison_mode",
        default="Separate",
        help="Side by Side: traditional layout. Separate: overlapping boxplots"
    )
    
    # Figure size controls
    col1, col2 = st.columns([1, 2])
    with col1:
        fig_size_mode = st.segmented_control(
            "Figure Size",
            ["Auto", "Manual"],
            key="fig_size_mode",
            default="Auto"
        )
        
    with col2:
        if fig_size_mode == "Manual":
            col_w, col_h = st.columns(2)
            with col_w:
                fig_width_cm = st.slider("Width (cm)", 4, 100, 40, 1, key="fig_width_cm")
            with col_h:
                fig_height_cm = st.slider("Height (cm)", 4, 100, 40, 1, key="fig_height_cm")
        else:
            fig_width_cm = None
            fig_height_cm = None
    
    # Output format selection
    output_format = st.segmented_control(
        "Output Format",
        ["PNG", "PDF"],
        key="output_format",
        default="PNG"
    )
    
    # Title controls
    show_titles = st.checkbox("Add titles to plots", value=False, key="show_titles")
    
    # If titles are enabled, show input fields for each subset
    plot_titles = {}
    if show_titles:
        st.write("Enter titles for each subset:")
        cols = st.columns(min(3, len(filenames)))
        for i, filename in enumerate(filenames):
            col_idx = i % len(cols)
            with cols[col_idx]:
                default_title = os.path.splitext(filename)[0]
                plot_titles[filename] = st.text_input(f"Title for {default_title}", 
                                                    value=default_title, 
                                                    key=f"title_{i}")
    
    # New feature: Combine plots
    combine_plots = False
    combined_plot_title = ""
    if len(dataframes) > 1:
        combine_plots = st.checkbox(
            "Combine plots into a single image", 
            value=False, 
            key="combine_plots", 
            # help="Combine all plots into a single grid image. Only available for multiple subsets."
        )
        if combine_plots:
            combined_plot_title = st.text_input(
                "Overall plot title", 
                value="", 
                key="combined_plot_title", 
                placeholder="Optional title for the combined plot"
            )
            st.segmented_control(
                "Grid Layout",
                ["Auto", "Manual"],
                key="grid_layout_mode",
                default="Auto"
            )
            if st.session_state.get("grid_layout_mode") == "Manual":
                col1, col2 = st.columns(2)
                with col1:
                    st.number_input("Rows", min_value=1, value=1, key="grid_rows")
                with col2:
                    st.number_input("Columns", min_value=1, value=1, key="grid_cols")

    # Generate plot button with styling
    st.markdown(
        """
        <style>
        div.stButton > button[kind="primary"] {
            background-color: #ff4b4b;
            color: white;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    if st.button("Generate Plot", key="generate_plot", type="primary"):
        # Convert secondary_dim to None if "None" is selected
        secondary_dimension = None if secondary_dim == "None" else secondary_dim
        
        st.session_state.last_plot_params = {
            'dataframes': dataframes,
            'filenames': filenames,
            'primary_dim': primary_dim,
            'secondary_dim': secondary_dimension,
            'y_axis': y_axis,
            'show_titles': show_titles,
            'comparison_mode': comparison_mode,
            'show_outliers': show_outliers,
            'fig_size_mode': fig_size_mode,
            'fig_width_cm': fig_width_cm,
            'fig_height_cm': fig_height_cm,
            'output_format': output_format,
            'plot_titles': plot_titles,
            'axes_label_mode': axes_label_mode,
            'x_label': x_label,
            'y_label': y_label,
            'primary_bin_edges': primary_bin_edges,
            'secondary_bin_edges': secondary_bin_edges,
            'primary_dim_order': primary_dim_order,
            'secondary_dim_order': secondary_dim_order,
            'combine_plots': combine_plots,
            'combined_plot_title': combined_plot_title,
            'grid_layout_mode': st.session_state.get('grid_layout_mode', 'Auto'),
            'grid_rows': st.session_state.get('grid_rows', 1),
            'grid_cols': st.session_state.get('grid_cols', 1)
        }
        # Clear any previous cache when generating a new plot
        if 'combined_plot_cache' in st.session_state:
            del st.session_state.combined_plot_cache
        if 'combined_plot_cache_key' in st.session_state:
            del st.session_state.combined_plot_cache_key


    # Show plots if they've been generated and parameters haven't changed
    if 'last_plot_params' in st.session_state:
        secondary_dimension = None if secondary_dim == "None" else secondary_dim
        current_params_check = {
            'dataframes': dataframes, 'filenames': filenames, 'primary_dim': primary_dim,
            'secondary_dim': secondary_dimension, 'y_axis': y_axis, 'show_titles': show_titles,
            'comparison_mode': comparison_mode, 'show_outliers': show_outliers,
            'fig_size_mode': fig_size_mode, 'fig_width_cm': fig_width_cm, 'fig_height_cm': fig_height_cm,
            'output_format': output_format, 'plot_titles': plot_titles, 'axes_label_mode': axes_label_mode,
            'x_label': x_label, 'y_label': y_label, 'primary_bin_edges': primary_bin_edges,
            'secondary_bin_edges': secondary_bin_edges,
            'primary_dim_order': primary_dim_order,
            'secondary_dim_order': secondary_dim_order,
            'combine_plots': combine_plots,
            'combined_plot_title': combined_plot_title,
            'grid_layout_mode': st.session_state.get('grid_layout_mode', 'Auto'),
            'grid_rows': st.session_state.get('grid_rows', 1),
            'grid_cols': st.session_state.get('grid_cols', 1)
        }
        
        params_for_comparison_current = current_params_check.copy()
        params_for_comparison_last = st.session_state.last_plot_params.copy()
        del params_for_comparison_current['dataframes']
        del params_for_comparison_last['dataframes']

        if not params_for_comparison_current != params_for_comparison_last:
            display_plots(**st.session_state.last_plot_params)

def display_plots(dataframes, filenames, primary_dim, secondary_dim, y_axis, 
                  show_titles=False, comparison_mode="Separate", 
                  show_outliers=False, fig_size_mode="Auto", fig_width_cm=None, 
                  fig_height_cm=None, output_format="PNG", plot_titles=None,
                  axes_label_mode="Auto", x_label=None, y_label=None,
                  primary_bin_edges=None, secondary_bin_edges=None,
                  primary_dim_order=None, secondary_dim_order=None,
                  combine_plots=False, combined_plot_title="",
                  grid_layout_mode="Auto", grid_rows=3, grid_cols=3):
    """
    Displays plots based on UI controls, either as a combined grid or individually.
    It calls logic functions to generate plot data and then handles the Streamlit UI rendering.
    """
    # If combine plots is selected, call the dedicated logic and display function
    if combine_plots and len(dataframes) > 1:
        display_combined_plot(
            dataframes=dataframes, filenames=filenames, primary_dim=primary_dim, 
            secondary_dim=secondary_dim, y_axis=y_axis, show_titles=show_titles, 
            comparison_mode=comparison_mode, show_outliers=show_outliers, 
            fig_size_mode=fig_size_mode, fig_width_cm=fig_width_cm, 
            fig_height_cm=fig_height_cm, output_format=output_format, 
            plot_titles=plot_titles, axes_label_mode=axes_label_mode, 
            x_label=x_label, y_label=y_label, primary_bin_edges=primary_bin_edges, 
            secondary_bin_edges=secondary_bin_edges,
            primary_dim_order=primary_dim_order,
            secondary_dim_order=secondary_dim_order,
            combined_plot_title=combined_plot_title,
            grid_layout_mode=grid_layout_mode, grid_rows=grid_rows, grid_cols=grid_cols
        )
        return

    # --- Display individual plots ---
    plot_buffers = []
    
    # Generate all figures first using the logic function
    figures_with_filenames = generate_plot_figures(
        dataframes, filenames, primary_dim, secondary_dim, y_axis,
        show_titles, plot_titles, comparison_mode, show_outliers,
        fig_size_mode, fig_width_cm, fig_height_cm,
        axes_label_mode, x_label, y_label,
        primary_bin_edges, secondary_bin_edges,
        primary_dim_order, secondary_dim_order
    )

    # Now, iterate and display each generated figure
    for file_idx, (fig, filename) in enumerate(figures_with_filenames):
        if fig is None: # Handle case where figure generation failed
            continue

        st.markdown(f"### {os.path.splitext(filename)[0]}")
        
        # Display the plot
        st.pyplot(fig)
        
        # Create download buffer
        buffer = save_plot_to_buffer(fig, format=output_format.lower())
        extension = "pdf" if output_format == "PDF" else "png"
        plot_buffers.append((buffer, f"{os.path.splitext(filename)[0]}.{extension}"))
        
        # Individual download button
        st.download_button(
            label=f"download as {output_format.lower()} : {os.path.splitext(filename)[0]}",
            data=buffer,
            file_name=f"{os.path.splitext(filename)[0]}_plot.{extension}",
            mime=f"image/{extension}",
            key=f"download_plot_{file_idx}"
        )
    
    # Add zip download option if multiple plots were successful
    if len(plot_buffers) > 1:
        create_zip_download(plot_buffers, output_format.lower())


def display_combined_plot(dataframes, filenames, **kwargs):
    """
    Handles the logic for displaying a combined plot, including caching.
    """
    # --- Manual Caching Logic ---
    # Create a hashable key from all function parameters.
    # The previous implementation failed because dicts (like plot_titles) and lists 
    # (like bin_edges) are not hashable and cannot be part of a cache key.
    
    # We now convert mutable items to their immutable, hashable counterparts.
    hashable_items = []
    # Sort by key to ensure the order is always consistent
    for key, value in sorted(kwargs.items()):
        if isinstance(value, dict):
            # Convert dict to a frozenset of its items
            hashable_items.append((key, frozenset(value.items())))
        elif isinstance(value, list):
            # Convert list to a tuple
            hashable_items.append((key, tuple(value)))
        else:
            # Assume other types are hashable
            hashable_items.append((key, value))
    
    cache_key = (
        tuple(filenames),
        tuple(hashable_items)
    )

    if st.session_state.get('combined_plot_cache_key') == cache_key:
        cached_data = st.session_state.combined_plot_cache
        st.image(cached_data['image'], caption="Combined Plot")
        st.download_button(**cached_data['download_args'])
        return
    # --- End of Caching Logic ---

    with st.spinner("Generating combined plot... This may take a moment."):
        # Call the logic function to do the heavy lifting
        final_image, download_args = generate_combined_plot_logic(
            dataframes=dataframes,
            filenames=filenames,
            **kwargs
        )

        if final_image and download_args:
            # Display and provide download
            st.image(final_image, caption="Combined Plot")
            st.download_button(**download_args)

            # Store results in the manual cache
            st.session_state.combined_plot_cache_key = cache_key
            st.session_state.combined_plot_cache = {
                'image': final_image,
                'download_args': download_args
            }

def create_zip_download(plot_buffers, format='png'):
    """Create a ZIP file containing all plots"""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED) as zip_file:
        for buffer, name in plot_buffers:
            zip_file.writestr(name, buffer.getvalue())
    
    zip_buffer.seek(0)
    st.download_button(
        label=f"download all as {format}",
        data=zip_buffer,
        file_name=f"all_plots.zip",
        mime="application/zip",
        key="download_all_plots"
    )